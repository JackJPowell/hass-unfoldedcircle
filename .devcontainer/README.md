## Developing with Visual Studio Code + devcontainer

The easiest way to get started with custom integration development is to use Visual Studio Code with devcontainers. This approach will create a preconfigured development environment with all the tools you need.

In the container you will have a dedicated Home Assistant core instance running with your custom component code. You can configure this instance by updating the `./config/configuration.yaml` file.

**Prerequisites**

- [git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)
- Docker
  - For Linux, macOS, or Windows 10 Pro/Enterprise/Education use the [current release version of Docker](https://docs.docker.com/install/)
  - Windows 10 Home requires [WSL 2](https://docs.microsoft.com/windows/wsl/wsl2-install) and the current Edge version of Docker Desktop (see instructions [here](https://docs.docker.com/docker-for-windows/wsl-tech-preview/)). This can also be used for Windows Pro/Enterprise/Education.
- [Visual Studio code](https://code.visualstudio.com/)
- [Remote - Containers (VSC Extension)][extension-link]

[More info about requirements and devcontainer in general](https://code.visualstudio.com/docs/remote/containers#_getting-started)

[extension-link]: https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers

**Getting started:**

1. Fork the repository.
2. Clone the repository to your computer.
3. Open the repository using Visual Studio code.

When you open this repository with Visual Studio code you are asked to "Reopen in Container", this will start the build of the container.

The container image includes Node.js and native build tools. Python dependencies
and Unfurled are installed from `requirements_all.txt` and `requirements_dev.txt`
when the container is created. After changing requirements, rebuild the container
and wait for the post-create setup to finish before starting Home Assistant.

Python packages are installed in the container's `/opt/venv` virtual environment.
The terminal and the `Home Assistant` debugger both use this interpreter; no manual
interpreter selection is needed after rebuilding. The environment is recreated
with the container, so it cannot retain packages from a previous Python version.
Setup checks `python -m homeassistant --version` and fails if Home Assistant cannot
start. To launch without the debugger, run `python -m homeassistant -c config`.

_If you don't see this notification, open the command palette and select `Dev Containers: Reopen Folder in Container`._

### Step by Step debugging

With the development container,
you can test your custom component in Home Assistant with step by step debugging.

Launch the debugger with the existing debugging configuration `Home Assistant`.
