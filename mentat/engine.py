import asyncio
import logging
import signal
from typing import Any, Dict, List, Set
from uuid import UUID

from ipdb import set_trace

from .session import Session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mentat.engine")


class Engine:
    """A global process and task manager.

    A client (Terminal, VSCode extension, NeoVim plugin, etc.) will use an `Engine`
    instance for any Mentat functionality.
    """

    def __init__(self, with_rpc_server: bool = False):
        self.sessions: Dict[UUID, Session] = {}

        self._should_exit = False
        self._force_exit = False
        self._tasks: Set[asyncio.Task] = set()

    # Session

    # async def session_create(
    #     self,
    #     paths: List[str] | None = [],
    #     exclude_paths: List[str] | None = [],
    #     no_code_map: bool = False,
    # ) -> UUID:
    #     session = Session(paths, exclude_paths, no_code_map)
    #     session.start()
    #     self.sessions[session.id] = session
    #
    #     return session.id

    # async def session_exists(self, session_id: UUID):
    #     return True if session_id in self.sessions else False

    # async def session_listen(self, session_id: UUID):
    #     if session_id not in self.sessions:
    #         raise Exception(f"Session {session_id} does not exist")
    #     session = self.sessions[session_id]
    #     async for message in session._session_conversation.listen():
    #         yield message

    async def session_send(
        self, session_id: UUID, content: Any, channel: str = "default", **kwargs
    ):
        if session_id not in self.sessions:
            raise Exception(f"Session {session_id} does not exist")
        session = self.sessions[session_id]
        message = await session._session_conversation.send_message(
            source="client", data=dict(content=content, **kwargs), channel=channel
        )

        return message.id

    # async def session_recv(self, session_id: UUID):
    #     if session_id not in self.sessions:
    #         raise Exception(f"Session {session_id} does not exist")

    async def get_session_code_context(self, session_id: UUID):
        if session_id not in self.sessions:
            raise Exception(f"Session {session_id} does not exist")
        session = self.sessions[session_id]
        code_context_file_paths = list(session.code_context.files.keys())

        return code_context_file_paths

    # Commands

    async def get_commands(self):
        ...

    async def run_command(self, command: str):
        ...

    ### lifecycle methods

    async def heartbeat(self):
        while True:
            logger.debug("heartbeat")
            await asyncio.sleep(3)

    def _handle_exit(self):
        print("got a signal")  # TODO: remove
        if self._should_exit:
            self._force_exit = True
        else:
            self._should_exit = True

    def _init_signal_handlers(self):
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGINT, self._handle_exit)
        loop.add_signal_handler(signal.SIGTERM, self._handle_exit)

    async def _startup(self):
        logger.debug("Starting Engine...")
        healthcheck_task = asyncio.create_task(self.heartbeat())
        self._tasks.add(healthcheck_task)

    async def _main_loop(self):
        logger.debug("Running Engine...")

        counter = 0
        while not self._should_exit:
            counter += 1
            counter = counter % 86400
            await asyncio.sleep(0.1)

    async def _shutdown(self):
        logger.debug("Shutting Engine down...")

        for task in self._tasks:
            task.cancel()
        logger.debug("Waiting for Jobs to finish. (CTRL+C to force quit)")
        while not self._force_exit:
            if all([task.cancelled() for task in self._tasks]):
                break
            await asyncio.sleep(0.1)

        if self._force_exit:
            logger.debug("Force exiting.")

        logger.debug("Engine has stopped")

    async def _run(self, install_signal_handlers: bool = True):
        try:
            if install_signal_handlers:
                self._init_signal_handlers()
            await self._startup()
            await self._main_loop()
            await self._shutdown()
        except:
            set_trace()
            pass

    def run(self, install_signal_handlers: bool = True):
        asyncio.run(self._run(install_signal_handlers=install_signal_handlers))


def run_cli():
    mentat_engine = Engine()
    mentat_engine.run()
