"""
Example usage of the enhanced JSON validation and prompt shorteners.
"""

from .claude import ClaudeClient
from .expansion import ExpansionProcessor, SmartTruncation
from .prompts import FilePreviewManager
from .types import ModelContext


def demonstrate_json_validation():
    """Demonstrate JSON validation and auto-repair capabilities."""
    print("=== JSON Validation Demo ===")
    
    client = ClaudeClient()
    
    # Test malformed JSON responses
    test_cases = [
        # Missing quotes around keys
        "{files_to_read: [main.py], commands_to_run: [ls], rationale: 'test'}",
        
        # Single quotes instead of double quotes
        "{'files_to_read': ['main.py'], 'commands_to_run': ['ls'], 'rationale': 'test'}",
        
        # Missing required fields
        "{'files_to_read': ['main.py']}",
        
        # Wrong types
        "{'files_to_read': 'main.py', 'commands_to_run': 'ls', 'rationale': 'test'}",
        
        # Completely malformed
        "I need to read main.py and run ls command to understand the codebase",
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest Case {i}: {test_case[:50]}...")
        try:
            plan = client._parse_plan_response(test_case)
            print(f"✅ Successfully parsed: {plan.files_to_read}")
        except Exception as e:
            print(f"❌ Failed: {e}")


def demonstrate_prompt_shorteners():
    """Demonstrate prompt shorteners and expansion capabilities."""
    print("\n=== Prompt Shorteners Demo ===")
    
    # Create a large file content for demonstration
    large_file_content = "\n".join([
        f"# Line {i}: This is a sample line of code" for i in range(1, 201)
    ])
    
    file_contents = {
        "main.py": large_file_content,
        "utils.py": "\n".join([f"def func_{i}(): pass" for i in range(1, 51)]),
        "config.py": "# Configuration file\nDEBUG = True\nPORT = 8000"
    }
    
    # Test basic truncation
    preview_manager = FilePreviewManager(default_max_lines=20)
    
    print("\n--- Basic Truncation ---")
    for filepath, content in file_contents.items():
        truncated = preview_manager.truncate_file_content(content, filepath, 20)
        print(f"\n{filepath} (truncated to 20 lines):")
        print(truncated[:200] + "..." if len(truncated) > 200 else truncated)
    
    # Test expansion
    print("\n--- Expansion Demo ---")
    print("Expanding main.py preview...")
    preview_manager.expand_file_preview("main.py", 100)
    
    expanded = preview_manager.truncate_file_content(large_file_content, "main.py", 100)
    print(f"main.py (expanded to 100 lines):")
    print(expanded[:300] + "..." if len(expanded) > 300 else expanded)
    
    # Test expansion processor
    print("\n--- Expansion Processor Demo ---")
    processor = ExpansionProcessor(preview_manager)
    
    test_requests = [
        "show me more of main.py",
        "expand utils.py",
        "show more config.py",
        "full content of main.py",
        "show me more of nonexistent.py"
    ]
    
    available_files = list(file_contents.keys())
    
    for request in test_requests:
        is_expansion, response, expanded_file = processor.process_expansion_request(
            request, available_files
        )
        print(f"Request: '{request}'")
        print(f"Response: {response}")
        if expanded_file:
            print(f"Expanded: {expanded_file}")
        print()


def demonstrate_smart_truncation():
    """Demonstrate smart truncation that preserves important code structures."""
    print("\n=== Smart Truncation Demo ===")
    
    # Create a Python file with various structures
    python_content = "\n".join([
        "import os",
        "import sys",
        "from typing import List, Dict",
        "",
        "class MyClass:",
        "    def __init__(self):",
        "        self.value = 42",
        "",
        "    def method1(self):",
        "        return self.value",
        "",
        "def function1():",
        "    return 'hello'",
        "",
        "def function2(param: str) -> str:",
        "    return param.upper()",
        "",
        "# Some comments",
        "CONSTANT = 100",
        "",
        "if __name__ == '__main__':",
        "    print('Hello world')",
    ] + [f"    # Additional line {i}" for i in range(1, 50)])
    
    preview_manager = FilePreviewManager()
    smart_truncation = SmartTruncation(preview_manager)
    
    print("Original file has 70+ lines")
    print("\nSmart truncation (preserving imports, functions, classes):")
    smart_truncated = smart_truncation.truncate_with_context(
        python_content, "example.py", max_lines=25
    )
    print(smart_truncated)


def demonstrate_integration():
    """Demonstrate full integration with ModelContext."""
    print("\n=== Full Integration Demo ===")
    
    # Create a realistic context
    context = ModelContext(
        task="Add error handling to the main function",
        repo_path="/path/to/project",
        file_contents={
            "main.py": "\n".join([f"line {i}" for i in range(1, 101)]),
            "utils.py": "\n".join([f"def util_{i}(): pass" for i in range(1, 26)]),
        },
        preview_max_lines=30,
        enable_smart_truncation=True
    )
    
    client = ClaudeClient()
    
    # Simulate the propose_patch method
    from .prompts import format_file_contents_with_expansion
    
    formatted_files = format_file_contents_with_expansion(
        context.file_contents,
        client.preview_manager,
        context.preview_max_lines
    )
    
    print("Formatted file contents with expansion hints:")
    print(formatted_files[:500] + "..." if len(formatted_files) > 500 else formatted_files)


if __name__ == "__main__":
    demonstrate_json_validation()
    demonstrate_prompt_shorteners()
    demonstrate_smart_truncation()
    demonstrate_integration()
