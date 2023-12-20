import importlib.util
import json
import os
import re

import pytest
from git import Repo
from openai.types.chat.completion_create_params import ResponseFormat

from mentat.llm_api_handler import model_context_size, prompt_tokens
from mentat.python_client.client import PythonClient
from mentat.session_context import SESSION_CONTEXT
from tests.benchmarks.benchmark_result import BenchmarkResult
from tests.benchmarks.benchmark_result_summary import BenchmarkResultSummary
from mentat.utils import clone_repo


def dynamic_import(path_to_module, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path_to_module)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pytestmark = pytest.mark.benchmark


@pytest.fixture
def retries(request):
    return int(request.config.getoption("--retries"))


async def grade(to_grade, prompt, model="gpt-4-1106-preview"):
    try:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": to_grade},
        ]
        tokens = prompt_tokens(messages, model)
        max_tokens = model_context_size(model) - 1000  # Response buffer
        if tokens > max_tokens:
            print("Prompt too long! Truncating... (this may affect results)")
            tokens_to_remove = tokens - max_tokens
            chars_per_token = len(str(messages)) / tokens
            chars_to_remove = int(chars_per_token * tokens_to_remove)
            messages[1]["content"] = messages[1]["content"][:-chars_to_remove]

        llm_api_handler = SESSION_CONTEXT.get().llm_api_handler
        llm_grade = await llm_api_handler.call_llm_api(
            messages, model, False, ResponseFormat(type="json_object")
        )
        content = llm_grade.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)}


syntax_grading_prompt = """\
You will be given a git diff that was generated by an automated system. Your job
is to flag certain common errors. Please reply with a json object with the
following schema:
off_by_one: true if you believe a line was inserted at the wrong place otherwise
false
The following two fields are only required if off_by_one is true:
off_by_one_lines: a list of line numbers that you believe were inserted at the
wrong place
off_by_one_direction: a list of integers that are how off you believe the
insertions were. A positive number means the line was inserted too low, a
negative numbers means to high.
indentation: true if you believe the indentation is incorrect otherwise false
The following two fields are only required if indentation is true:
indentation_lines: a list of line numbers that you believe have incorrect
indentation.
indentation_direction: a list of integers that are how off you believe the
indentation is. A positive number means the line was indented too far, a
negative number means not enough.
syntax: true if you believe there is a syntax error unrelated to insertion
location or indentation.
syntax_description: a string describing the syntax errors if present."""


async def grade_diff_syntax(diff):
    return await grade(diff, syntax_grading_prompt)


model_response_grade_prompt = """\
You will be give a models response to a prompt. You won't be given the full
context of the response. You are just looking for certain stylistic errors.
Respond in json. The following fields are required:
referenced_format: boolean, true if the model talks about its edit format in any
way in its response. For example if it has a clause like "The edits in the
requested format are:"
trailing_waffling: boolean, true if after the structured edits the model ends
with a clause like "Please note I may not have had all the information I needed" """


async def grade_model_response(model_response):
    return await grade(model_response, model_response_grade_prompt)


comparison_prompt = """\
You will be given two diffs. The first was human written and the second was
generated by an automated system. Your job is to grade the automated diff. Repond in
json. The following fields are required:
missing_functionality: true if the generated diff is missing functionality
present in the human written pr.
missing_description: optional string describing what's missing
extra_functionality: true if the generated diff has functionality not present
in the human written pr.
extra_description: optional string describing what's extra"""


async def compare_diffs(actual, generated):
    prompt = f"HUMAN WRITTEN DIFF:\n{actual}\nGENERATED DIFF:\n{generated}"

    return await grade(prompt, comparison_prompt)


@pytest.mark.asyncio
async def test_benchmark(retries, benchmarks):
    print("Running benchmarks")
    benchmarks_dir = f"{os.path.dirname(__file__)}/benchmarks"

    benchmark_paths = []
    for root, dirs, files in os.walk(benchmarks_dir):
        for file in files:
            if file.endswith(".py"):
                benchmark_paths.append(os.path.join(root, file))

    print("Found benchmarks:\n" + "\n".join(benchmark_paths))
    results = []
    for path in benchmark_paths:
        benchmark = dynamic_import(path, "benchmark")
        title = benchmark.title

        run = True
        if len(benchmarks) > 0:
            run = False
            for b in benchmarks:
                if b.lower() in title.lower():
                    run = True
                    break
        if not run:
            continue

        print("Benchmark:", title)

        codebase = clone_repo(
            url=benchmark.repo,
            local_dir_name=benchmark.repo.split("/")[-1],
            refresh=False,
        )

        os.chdir(codebase)
        repo = Repo(".")
        start_commit = repo.commit()
        repo.git.checkout(benchmark.commit)

        for i, prompt in enumerate(benchmark.prompts):
            print("  Prompt:", prompt)
            for j in range(1, retries + 1):
                formatted_title = re.sub(r"[ '\"/\\-^]", "", title).replace(" ", "_")
                result = BenchmarkResult(
                    name=f"{formatted_title}-{i}-{j}",
                    family=formatted_title,
                )
                client = PythonClient(cwd=codebase, config=benchmark.config)
                await client.startup()
                response = await client.call_mentat(prompt)
                await client.call_mentat("y")
                await client.wait_for_edit_completion()

                await client.call_mentat("q")
                messages = client.get_conversation().literal_messages
                cost_tracker = client.get_cost_tracker()
                result.cost = cost_tracker.total_cost
                result.tokens = cost_tracker.total_tokens
                result.transcript = {
                    "id": result.name,
                    "messages": messages,
                }

                await client.shutdown()
                repo.git.add(["--all"])

                if hasattr(benchmark, "verify"):
                    result.verify = benchmark.verify()

                # Set syntax and response grade information
                diff = repo.git.diff(["--staged"])
                result.code = diff
                diff_grade = await grade_diff_syntax(diff)
                result.diff_grade = diff_grade
                result.off_by_one = diff_grade.get("off_by_one")
                result.indentation_error = diff_grade.get("indentation")
                result.syntax_error = diff_grade.get("syntax")
                response_grade = await grade_model_response(response)
                result.response_grade = response_grade
                result.referenced_format = response_grade.get("referenced_format")

                # Clean up
                repo.git.reset("--hard")
                repo.git.clean("-fd")
                results.append(result)

                # Set comparison grade information
                if hasattr(benchmark, "comparison_commit"):
                    repo.git.checkout(benchmark.comparison_commit)
                    comparison_diff = repo.git.diff(benchmark.commit)
                    comparison_grade = await compare_diffs(diff, comparison_diff)
                    result.comparison_grade = comparison_grade
                    result.extra_functionality = comparison_grade.get(
                        "extra_functionality"
                    )
                    result.missing_functionality = comparison_grade.get(
                        "missing_functionality"
                    )
        repo.git.checkout(start_commit)

    summary = BenchmarkResultSummary(results)
    os.chdir("../..")
    with open("results.json", "w") as f:
        f.write(summary.to_json())
    summary.render_results()
