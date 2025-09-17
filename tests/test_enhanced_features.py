"""Tests for enhanced JSON validation and prompt shorteners."""

import pytest

from kevin.models.claude import ClaudeClient
from kevin.models.expansion import ExpansionProcessor
from kevin.models.prompts import FilePreviewManager
from kevin.models.types import ModelContext, Plan, Reflection
from kevin.models.validation import DiffValidator, JSONValidator


class TestJSONValidation:
    """Test JSON validation and auto-repair functionality."""

    def test_valid_json_parsing(self):
        """Test parsing of valid JSON responses."""
        validator = JSONValidator()
        
        valid_json = '{"files_to_read": ["main.py"], "commands_to_run": ["ls"], "rationale": "test"}'
        plan = validator.validate_and_repair_json(valid_json, "plan", Plan)
        
        assert plan.files_to_read == ["main.py"]
        assert plan.commands_to_run == ["ls"]
        assert plan.rationale == "test"

    def test_malformed_json_repair(self):
        """Test auto-repair of malformed JSON."""
        validator = JSONValidator()
        
        # Missing quotes around keys
        malformed = "{files_to_read: [main.py], commands_to_run: [ls], rationale: 'test'}"
        plan = validator.validate_and_repair_json(malformed, "plan", Plan)
        
        assert plan.files_to_read == ["main.py"]
        assert plan.commands_to_run == ["ls"]

    def test_missing_fields_repair(self):
        """Test auto-repair when required fields are missing."""
        validator = JSONValidator()
        
        # Missing required fields
        incomplete = '{"files_to_read": ["main.py"]}'
        plan = validator.validate_and_repair_json(incomplete, "plan", Plan)
        
        assert plan.files_to_read == ["main.py"]
        assert plan.commands_to_run  # Should have default value
        assert plan.rationale  # Should have default value

    def test_wrong_types_repair(self):
        """Test auto-repair when field types are wrong."""
        validator = JSONValidator()
        
        # Wrong types
        wrong_types = '{"files_to_read": "main.py", "commands_to_run": "ls", "rationale": "test"}'
        plan = validator.validate_and_repair_json(wrong_types, "plan", Plan)
        
        assert isinstance(plan.files_to_read, list)
        assert isinstance(plan.commands_to_run, list)

    def test_reflection_validation(self):
        """Test reflection response validation."""
        validator = JSONValidator()
        
        reflection_json = '{"next_action": "retry", "lessons_learned": "test", "should_retry": true}'
        reflection = validator.validate_and_repair_json(reflection_json, "reflection", Reflection)
        
        assert reflection.next_action == "retry"
        assert reflection.lessons_learned == "test"
        assert reflection.should_retry is True


class TestDiffValidation:
    """Test diff validation and auto-repair functionality."""

    def test_valid_diff(self):
        """Test validation of valid unified diff."""
        validator = DiffValidator()
        
        valid_diff = """--- a/main.py
+++ b/main.py
@@ -1,3 +1,3 @@
 def main():
-    print("hello")
+    print("world")
"""
        result = validator.validate_and_repair_diff(valid_diff)
        assert "---" in result
        assert "+++" in result
        assert "@@" in result

    def test_markdown_cleanup(self):
        """Test cleanup of markdown formatting."""
        validator = DiffValidator()
        
        markdown_diff = """```diff
--- a/main.py
+++ b/main.py
@@ -1,3 +1,3 @@
 def main():
-    print("hello")
+    print("world")
```
"""
        result = validator.validate_and_repair_diff(markdown_diff)
        assert not result.startswith("```")
        assert not result.endswith("```")

    def test_malformed_diff_repair(self):
        """Test repair of malformed diff."""
        validator = DiffValidator()
        
        malformed = """def main():
-    print("hello")
+    print("world")
"""
        result = validator.validate_and_repair_diff(malformed)
        assert "---" in result
        assert "+++" in result


class TestFilePreviewManager:
    """Test file preview management functionality."""

    def test_basic_truncation(self):
        """Test basic file content truncation."""
        manager = FilePreviewManager(default_max_lines=10)
        
        # Create content with 20 lines
        content = "\n".join([f"line {i}" for i in range(1, 21)])
        
        truncated = manager.truncate_file_content(content, "test.py", 10)
        lines = truncated.split("\n")
        
        assert len(lines) <= 12  # 10 content lines + 2 indicator lines
        assert "... (10 lines omitted) ..." in truncated
        assert "[SHOW_MORE:test.py:20]" in truncated

    def test_no_truncation_needed(self):
        """Test when truncation is not needed."""
        manager = FilePreviewManager(default_max_lines=50)
        
        content = "\n".join([f"line {i}" for i in range(1, 11)])
        truncated = manager.truncate_file_content(content, "test.py", 50)
        
        assert truncated == content
        assert "[SHOW_MORE:" not in truncated

    def test_expansion(self):
        """Test file preview expansion."""
        manager = FilePreviewManager(default_max_lines=10)
        
        content = "\n".join([f"line {i}" for i in range(1, 21)])
        
        # First truncation
        truncated = manager.truncate_file_content(content, "test.py", 10)
        assert "[SHOW_MORE:test.py:20]" in truncated
        
        # Expand
        manager.expand_file_preview("test.py", 20)
        expanded = manager.truncate_file_content(content, "test.py", 20)
        
        assert expanded == content
        assert "[SHOW_MORE:" not in expanded

    def test_expansion_hints(self):
        """Test extraction of expansion hints."""
        manager = FilePreviewManager()
        
        content = "line 1\n[SHOW_MORE:test.py:100]\nline 2"
        hints = manager.get_expansion_hints(content)
        
        assert "test.py:100" in hints


class TestExpansionProcessor:
    """Test expansion request processing."""

    def test_expansion_request_detection(self):
        """Test detection of expansion requests."""
        manager = FilePreviewManager()
        processor = ExpansionProcessor(manager)
        
        available_files = ["main.py", "utils.py", "config.py"]
        
        # Test various expansion request patterns
        test_cases = [
            ("show me more of main.py", True, "main.py"),
            ("expand utils.py", True, "utils.py"),
            ("show more config.py", True, "config.py"),
            ("full content of main.py", True, "main.py"),
            ("just a regular request", False, None),
        ]
        
        for request, should_be_expansion, expected_file in test_cases:
            is_expansion, response, expanded_file = processor.process_expansion_request(
                request, available_files
            )
            assert is_expansion == should_be_expansion
            if should_be_expansion:
                assert expanded_file == expected_file

    def test_file_matching(self):
        """Test file matching logic."""
        manager = FilePreviewManager()
        processor = ExpansionProcessor(manager)
        
        available_files = ["src/main.py", "src/utils.py", "config.json"]
        
        # Test exact match
        assert processor._find_matching_file("src/main.py", available_files) == "src/main.py"
        
        # Test filename match
        assert processor._find_matching_file("main.py", available_files) == "src/main.py"
        
        # Test partial match
        assert processor._find_matching_file("main", available_files) == "src/main.py"
        
        # Test extension match
        assert processor._find_matching_file("config", available_files) == "config.json"

    def test_nonexistent_file(self):
        """Test handling of nonexistent file requests."""
        manager = FilePreviewManager()
        processor = ExpansionProcessor(manager)
        
        available_files = ["main.py"]
        
        is_expansion, response, expanded_file = processor.process_expansion_request(
            "show me more of nonexistent.py", available_files
        )
        
        assert is_expansion is True
        assert expanded_file is None
        assert "not found" in response


class TestIntegration:
    """Test integration of all components."""

    def test_claude_client_integration(self):
        """Test ClaudeClient with new features."""
        client = ClaudeClient()
        
        # Test that validators are initialized
        assert hasattr(client, 'json_validator')
        assert hasattr(client, 'diff_validator')
        assert hasattr(client, 'preview_manager')
        
        # Test expansion methods
        client.expand_file_preview("test.py", 100)
        assert "test.py" in client.preview_manager.expanded_files
        
        client.reset_preview_expansions()
        assert len(client.preview_manager.expanded_files) == 0

    def test_model_context_integration(self):
        """Test ModelContext with new fields."""
        context = ModelContext(
            task="test task",
            repo_path="/test",
            preview_max_lines=30,
            enable_smart_truncation=True
        )
        
        assert context.preview_max_lines == 30
        assert context.enable_smart_truncation is True


if __name__ == "__main__":
    pytest.main([__file__])
