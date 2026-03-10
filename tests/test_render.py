from ftl.render import AgentRenderer


class FakeConsole:
    def __init__(self):
        self.lines = []

    def print(self, message="", *args, **kwargs):
        self.lines.append(str(message))


def test_renderer_treats_json_scalars_as_plain_text():
    console = FakeConsole()
    renderer = AgentRenderer(console)

    renderer.feed("0")

    assert console.lines == ["0"]
