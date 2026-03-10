from ftl.sandbox.docker import DockerSandbox, AGENT_IMAGES, _DEFAULT_IMAGE


def create_sandbox(agent="claude-code", backend="docker"):
    if backend == "docker":
        image = AGENT_IMAGES.get(agent, _DEFAULT_IMAGE)
        return DockerSandbox(image=image, agent_name=agent)
    raise ValueError(f"Unknown sandbox backend: {backend}")
