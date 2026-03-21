"""Tests for app.tool.builtin.code_execute — blocked import checking and execution."""

from __future__ import annotations

import pytest

from app.schemas.agent import AgentInfo
from app.tool.builtin.code_execute import CodeExecuteTool, _check_blocked_imports
from app.tool.context import ToolContext


def _make_ctx() -> ToolContext:
    return ToolContext(
        session_id="test-session",
        message_id="test-msg",
        agent=AgentInfo(name="test", description="", mode="primary"),
        call_id="test-call",
    )


class TestBlockedImports:
    def test_subprocess_blocked(self):
        assert _check_blocked_imports("import subprocess") is not None

    def test_shutil_blocked(self):
        assert _check_blocked_imports("import shutil") is not None

    def test_socket_blocked(self):
        assert _check_blocked_imports("import socket") is not None

    def test_submodule_blocked(self):
        assert _check_blocked_imports("from http.server import HTTPServer") is not None

    def test_allowed_import(self):
        assert _check_blocked_imports("import pandas") is None

    def test_indented_import_blocked(self):
        assert _check_blocked_imports("    import subprocess") is not None

    def test_from_import_blocked(self):
        assert _check_blocked_imports("from subprocess import run") is not None

    def test_comment_not_blocked(self):
        assert _check_blocked_imports("# import subprocess") is None


class TestCodeExecuteExecution:
    @pytest.fixture
    def tool(self):
        return CodeExecuteTool()

    @pytest.mark.asyncio
    async def test_simple_print(self, tool: CodeExecuteTool):
        result = await tool.execute({"code": "print('hello')"}, _make_ctx())
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_unicode_print(self, tool: CodeExecuteTool):
        """Ensure Chinese/Unicode characters are not garbled."""
        result = await tool.execute(
            {"code": "print('你好世界')"}, _make_ctx()
        )
        assert "你好世界" in result.output
