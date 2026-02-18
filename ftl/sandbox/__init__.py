from ftl.sandbox.docker import DockerSandbox


def create_sandbox(backend="docker"):
    if backend == "docker":
        return DockerSandbox()
    raise ValueError(f"Unknown sandbox backend: {backend}")
