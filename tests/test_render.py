import io

from ftl.render import AgentRenderer, TokenLagWriter


class FakeConsole:
    def __init__(self):
        self.file = io.StringIO()
        self.lines = []

    def print(self, message="", *args, **kwargs):
        self.lines.append(str(message))


def test_token_lag_writer_keeps_trailing_tokens_until_flush():
    console = FakeConsole()
    writer = TokenLagWriter(console, lag_tokens=2, cadence=0)

    writer.push("alpha beta gamma")

    assert console.file.getvalue() == "alpha "

    writer.flush()

    assert console.file.getvalue() == "alpha beta gamma"


def test_renderer_treats_json_scalars_as_plain_text():
    console = FakeConsole()
    renderer = AgentRenderer(console, stream_lag_tokens=0, stream_cadence=0)

    renderer.feed("0")
    renderer.finish()

    assert console.file.getvalue() == "0\n"
    assert console.lines == []


def test_renderer_streams_plain_text_and_flushes_on_finish():
    console = FakeConsole()
    renderer = AgentRenderer(console, stream_lag_tokens=2, stream_cadence=0)

    renderer.feed("hello there from ftl")

    assert console.file.getvalue() == "hello there "

    renderer.finish()

    assert console.file.getvalue() == "hello there from ftl\n"


def test_renderer_finish_adds_trailing_newline_when_missing():
    console = FakeConsole()
    renderer = AgentRenderer(console, stream_lag_tokens=0, stream_cadence=0)

    renderer.feed('{"type":"assistant","message":{"content":[{"type":"text","text":"done without newline"}]}}')
    renderer.finish()

    assert console.file.getvalue() == "done without newline\n"


def test_renderer_flushes_text_before_tool_status():
    console = FakeConsole()
    renderer = AgentRenderer(console, stream_lag_tokens=3, stream_cadence=0)

    renderer.feed('{"type":"assistant","message":{"content":[{"type":"text","text":"hello from agent "},{"type":"tool_use","name":"Read","input":{"file_path":"app.py"}}]}}')
    renderer.feed('{"type":"result"}')

    assert console.file.getvalue().startswith("hello from agent ")
    assert console.lines
    assert "Read: app.py" in console.lines[0]
