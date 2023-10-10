import * as vscode from "vscode";

function getNonce() {
  let text = "";
  const possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}

class WebviewProvider implements vscode.WebviewViewProvider {
  public name: string;
  private extensionUri: vscode.Uri;
  private _view?: vscode.WebviewView;
  private view?: vscode.WebviewView;
  private doc?: vscode.TextDocument;

  constructor(name: string, extensionUri: vscode.Uri) {
    this.name = name;
    this.extensionUri = extensionUri;
  }

  private getHtmlForWebview(webview: vscode.Webview) {
    console.log("GETTING HTML");

    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "build/webviews", `${this.name}.js`)
    );

    // Use a nonce to only allow specific scripts to be run
    const nonce = getNonce();

    const html = `
      <!DOCTYPE html>
      <html lang="en">
          <head>
              <meta charset="UTF-8">
              <!--
                  Use a content security policy to only allow loading images from https or from our extension directory,
                  and only allow scripts that have a specific nonce.
              -->
              <meta http-equiv="Content-Security-Policy" content="img-src https: data:; style-src 'unsafe-inline' ${webview.cspSource}; script-src 'nonce-${nonce}';">
                  <meta name="viewport" content="width=device-width, initial-scale=1.0">
          </head>
          <body>
          </body>
          <script nonce="${nonce}" src="${scriptUri}"></script>
      </html>
    `;

    return html;
  }

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ) {
    this.view = webviewView;
    this._view = webviewView;
    console.log("RESOLVING WEBVIEW");

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extensionUri],
    };
    webviewView.webview.html = this.getHtmlForWebview(webviewView.webview);
  }
}

export { WebviewProvider };
