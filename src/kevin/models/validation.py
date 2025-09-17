from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ValidationError


class JSONValidator:
    """Enhanced JSON validation with schema validation and auto-repair capabilities."""

    def __init__(self):
        self.schemas = {
            "plan": {
                "type": "object",
                "required": ["files_to_read", "commands_to_run", "rationale"],
                "properties": {
                    "files_to_read": {"type": "array", "items": {"type": "string"}},
                    "commands_to_run": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                },
            },
            "reflection": {
                "type": "object",
                "required": ["next_action", "lessons_learned", "should_retry"],
                "properties": {
                    "next_action": {"type": "string"},
                    "lessons_learned": {"type": "string"},
                    "should_retry": {"type": "boolean"},
                },
            },
        }

    def validate_and_repair_json(
        self, text: str, expected_schema: str, model_class: type[BaseModel]
    ) -> BaseModel:
        """
        Validate JSON against schema and auto-repair if needed.

        Args:
            text: Raw text response from model
            expected_schema: Schema name to validate against
            model_class: Pydantic model class to instantiate

        Returns:
            Validated and repaired model instance
        """
        # Step 1: Extract JSON from text
        json_data = self._extract_json(text)

        # Step 2: Validate against schema
        if self._validate_schema(json_data, expected_schema):
            try:
                return model_class(**json_data)
            except ValidationError as e:
                # Step 3: Auto-repair if schema validation passes but model validation fails
                repaired_data = self._repair_model_data(json_data, model_class, e)
                return model_class(**repaired_data)
        else:
            # Step 4: Auto-repair if schema validation fails
            repaired_data = self._repair_schema_data(json_data, expected_schema)
            return model_class(**repaired_data)

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Extract JSON object from text using multiple strategies."""
        # Strategy 1: Look for complete JSON object
        json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Strategy 2: Look for JSON with potential formatting issues
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            # Try to fix common JSON issues
            json_str = self._fix_common_json_issues(json_str)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # Strategy 3: Extract key-value pairs using regex
        return self._extract_key_value_pairs(text)

    def _fix_common_json_issues(self, json_str: str) -> str:
        """Fix common JSON formatting issues."""
        # Remove trailing commas
        json_str = re.sub(r",(\s*[}\]])", r"\1", json_str)

        # Fix single quotes to double quotes
        json_str = re.sub(r"'([^']*)'", r'"\1"', json_str)

        # Fix unquoted keys
        json_str = re.sub(r"(\w+):", r'"\1":', json_str)

        # Fix boolean values
        json_str = re.sub(r"\bTrue\b", "true", json_str)
        json_str = re.sub(r"\bFalse\b", "false", json_str)
        json_str = re.sub(r"\bNone\b", "null", json_str)

        return json_str

    def _extract_key_value_pairs(self, text: str) -> Dict[str, Any]:
        """Extract key-value pairs using regex patterns."""
        data = {}

        # Pattern for quoted keys and values
        pattern = r'"([^"]+)"\s*:\s*"([^"]*)"'
        matches = re.findall(pattern, text)
        for key, value in matches:
            data[key] = value

        # Pattern for boolean values
        bool_pattern = r'"([^"]+)"\s*:\s*(true|false)'
        bool_matches = re.findall(bool_pattern, text, re.IGNORECASE)
        for key, value in bool_matches:
            data[key] = value.lower() == "true"

        # Pattern for arrays - more flexible
        array_pattern = r'"([^"]+)"\s*:\s*\[(.*?)\]'
        array_matches = re.findall(array_pattern, text, re.DOTALL)
        for key, array_content in array_matches:
            # Simple array parsing - split by comma and clean up
            items = [item.strip().strip("\"'") for item in array_content.split(",")]
            data[key] = [item for item in items if item]

        # Pattern for unquoted arrays (like our test case)
        unquoted_array_pattern = r"(\w+)\s*:\s*\[(.*?)\]"
        unquoted_matches = re.findall(unquoted_array_pattern, text, re.DOTALL)
        for key, array_content in unquoted_matches:
            items = [item.strip().strip("\"'") for item in array_content.split(",")]
            data[key] = [item for item in items if item]

        # Pattern for unquoted strings
        unquoted_string_pattern = r"(\w+)\s*:\s*([^,\[\]]+)"
        unquoted_string_matches = re.findall(unquoted_string_pattern, text)
        for key, value in unquoted_string_matches:
            value = value.strip().strip("\"'")
            if key not in data:  # Don't override existing values
                data[key] = value

        return data

    def _validate_schema(self, data: Dict[str, Any], schema_name: str) -> bool:
        """Basic schema validation."""
        if schema_name not in self.schemas:
            return True  # No schema to validate against

        schema = self.schemas[schema_name]
        required_fields = schema.get("required", [])

        # Check required fields
        for field in required_fields:
            if field not in data:
                return False

        # Check field types
        properties = schema.get("properties", {})
        for field, field_schema in properties.items():
            if field in data:
                expected_type = field_schema.get("type")
                if expected_type == "array" and not isinstance(data[field], list):
                    return False
                elif expected_type == "string" and not isinstance(data[field], str):
                    return False
                elif expected_type == "boolean" and not isinstance(data[field], bool):
                    return False

        return True

    def _repair_schema_data(self, data: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
        """Repair data to match schema requirements."""
        if schema_name not in self.schemas:
            return data

        schema = self.schemas[schema_name]
        required_fields = schema.get("required", [])
        properties = schema.get("properties", {})

        repaired = data.copy()

        # Add missing required fields with defaults
        for field in required_fields:
            if field not in repaired:
                field_schema = properties.get(field, {})
                field_type = field_schema.get("type")

                if field_type == "array":
                    # Provide meaningful defaults for arrays
                    if field == "files_to_read":
                        repaired[field] = ["README.md", "main.py"]
                    elif field == "commands_to_run":
                        repaired[field] = ["ls -la", "git status"]
                    else:
                        repaired[field] = []
                elif field_type == "string":
                    repaired[field] = f"Auto-generated {field}"
                elif field_type == "boolean":
                    repaired[field] = True

        # Fix type mismatches
        for field, field_schema in properties.items():
            if field in repaired:
                field_type = field_schema.get("type")
                value = repaired[field]

                if field_type == "array" and not isinstance(value, list):
                    if isinstance(value, str):
                        # Try to split string into array
                        repaired[field] = [item.strip() for item in value.split(",")]
                    else:
                        repaired[field] = [str(value)]
                elif field_type == "string" and not isinstance(value, str):
                    repaired[field] = str(value)
                elif field_type == "boolean" and not isinstance(value, bool):
                    if isinstance(value, str):
                        repaired[field] = value.lower() in ("true", "yes", "1")
                    else:
                        repaired[field] = bool(value)

        return repaired

    def _repair_model_data(
        self, data: Dict[str, Any], model_class: type[BaseModel], error: ValidationError
    ) -> Dict[str, Any]:
        """Repair data based on Pydantic validation errors."""
        repaired = data.copy()

        # Get field information from the model
        model_fields = model_class.__fields__

        for error_detail in error.errors():
            field_name = error_detail.get("loc", [""])[0]
            error_type = error_detail.get("type")

            if field_name in model_fields:
                field_info = model_fields[field_name]
                field_type = field_info.type_

                if error_type == "value_error.missing":
                    # Add missing field with default
                    if hasattr(field_info, "default") and field_info.default is not None:
                        repaired[field_name] = field_info.default
                    elif field_type == list:
                        repaired[field_name] = []
                    elif field_type == str:
                        repaired[field_name] = f"Auto-generated {field_name}"
                    elif field_type == bool:
                        repaired[field_name] = True

                elif error_type in ["type_error.str", "type_error.integer", "type_error.boolean"]:
                    # Fix type conversion
                    if field_type == str:
                        repaired[field_name] = str(repaired.get(field_name, ""))
                    elif field_type == int:
                        try:
                            repaired[field_name] = int(repaired.get(field_name, 0))
                        except (ValueError, TypeError):
                            repaired[field_name] = 0
                    elif field_type == bool:
                        value = repaired.get(field_name, False)
                        if isinstance(value, str):
                            repaired[field_name] = value.lower() in ("true", "yes", "1")
                        else:
                            repaired[field_name] = bool(value)

        return repaired


class DiffValidator:
    """Validate and repair unified diff patches."""

    def __init__(self):
        self.diff_patterns = {
            "file_header": re.compile(r"^(---|\+\+\+)\s+(.+)"),
            "hunk_header": re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@"),
            "context_line": re.compile(r"^(\s)(.+)"),
            "addition": re.compile(r"^(\+)(.+)"),
            "deletion": re.compile(r"^(-)(.+)"),
        }

    def validate_and_repair_diff(self, diff_text: str) -> str:
        """
        Validate and repair unified diff format.

        Args:
            diff_text: Raw diff text

        Returns:
            Repaired diff text
        """
        # Clean up the response - remove any markdown formatting
        cleaned = diff_text.strip()
        if cleaned.startswith("```"):
            # Remove markdown code fences
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        # Validate diff structure
        if self._is_valid_diff(cleaned):
            return cleaned

        # Try to repair the diff
        return self._repair_diff(cleaned)

    def _is_valid_diff(self, diff_text: str) -> bool:
        """Check if diff text is in valid unified diff format."""
        lines = diff_text.strip().split("\n")
        if not lines:
            return False

        has_file_headers = False
        has_hunk_headers = False

        for line in lines:
            if self.diff_patterns["file_header"].match(line):
                has_file_headers = True
            elif self.diff_patterns["hunk_header"].match(line):
                has_hunk_headers = True

        return has_file_headers and has_hunk_headers

    def _repair_diff(self, diff_text: str) -> str:
        """Attempt to repair malformed diff."""
        lines = diff_text.strip().split("\n")
        repaired_lines = []

        # Look for file paths in the text
        file_paths = self._extract_file_paths(diff_text)

        if not file_paths:
            # If no file paths found, create a basic diff structure
            return self._create_basic_diff(diff_text)

        # Try to reconstruct the diff with proper headers
        current_file = file_paths[0]
        repaired_lines.append(f"--- a/{current_file}")
        repaired_lines.append(f"+++ b/{current_file}")
        repaired_lines.append("@@ -1,1 +1,1 @@")

        # Add the content lines
        for line in lines:
            if line.strip() and not line.startswith(("---", "+++", "@@")):
                if line.startswith("+") or line.startswith("-"):
                    repaired_lines.append(line)
                else:
                    repaired_lines.append(f" {line}")

        return "\n".join(repaired_lines)

    def _extract_file_paths(self, text: str) -> List[str]:
        """Extract potential file paths from text."""
        # Look for common file patterns
        patterns = [
            r"(\w+\.\w+)",  # filename.extension
            r"([a-zA-Z0-9_/]+\.py)",  # Python files
            r"([a-zA-Z0-9_/]+\.js)",  # JavaScript files
            r"([a-zA-Z0-9_/]+\.ts)",  # TypeScript files
        ]

        file_paths = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            file_paths.extend(matches)

        return list(set(file_paths))  # Remove duplicates

    def _create_basic_diff(self, content: str) -> str:
        """Create a basic diff structure when file paths can't be determined."""
        lines = content.strip().split("\n")

        # Try to determine if this is an addition or modification
        has_additions = any(line.startswith("+") for line in lines)
        has_deletions = any(line.startswith("-") for line in lines)

        if has_additions and not has_deletions:
            # Pure addition
            diff_lines = ["--- /dev/null", "+++ b/new_file"]
        elif has_deletions and not has_additions:
            # Pure deletion
            diff_lines = ["--- a/existing_file", "+++ /dev/null"]
        else:
            # Modification
            diff_lines = ["--- a/existing_file", "+++ b/existing_file"]

        diff_lines.append("@@ -1,1 +1,1 @@")

        # Add content lines
        for line in lines:
            if line.strip():
                if not line.startswith(("+", "-", " ")):
                    # Add context marker if missing
                    diff_lines.append(f" {line}")
                else:
                    diff_lines.append(line)

        return "\n".join(diff_lines)
