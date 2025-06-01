#!/usr/bin/env python3
"""
Title case checker for enforcing sentence case in documentation and templates.

This script checks for titles that should be in sentence case and reports violations.
It supports multiple file formats and allows for flexible exception handling.

Usage:
    python scripts/title_case_check.py                    # Check all files
    python scripts/title_case_check.py --fix              # Auto-fix violations
    python scripts/title_case_check.py --check-only       # Only report, don't fix
    python scripts/title_case_check.py templates/         # Check specific directory
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Union

try:
    import pathspec
except ImportError:
    pathspec = None


class TitleCaseChecker:
    """Check and optionally fix title case violations."""

    # Patterns for different file types
    PATTERNS = {
        "markdown": [
            (r"^(#{1,6})\s+(.+)$", "markdown_header"),
            (r"<h([1-6]).*?>(.*?)</h\1>", "html_header_in_md"),
        ],
        "html": [
            (r"<h([1-6])[^>]*>(.*?)</h\1>", "html_header"),
            (r"<title[^>]*>(.*?)</title>", "html_title"),
            (r"<label[^>]*>(.*?)</label>", "html_label"),
            (r"<button[^>]*>(.*?)</button>", "html_button"),
            (r"<a[^>]*>(.*?)</a>", "html_link"),
            (r"<strong[^>]*>(.*?)</strong>", "html_strong"),
            (r"<b[^>]*>(.*?)</b>", "html_bold"),
            # Standalone text patterns that look like labels (word/phrase followed by colon)
            (r"\b([A-Z][a-zA-Z\s]+):\s*", "standalone_label"),
        ],
        "jinja": [
            (r"<h([1-6])[^>]*>(.*?)</h\1>", "html_header"),
            (r"<title[^>]*>(.*?)</title>", "html_title"),
            (r"{%\s*block\s+title\s*%}(.*?){%\s*endblock\s*%}", "jinja_title_block"),
            (r"<label[^>]*>(.*?)</label>", "html_label"),
            (r"<button[^>]*>(.*?)</button>", "html_button"),
            (r"<a[^>]*>(.*?)</a>", "html_link"),
            (r"<strong[^>]*>(.*?)</strong>", "html_strong"),
            (r"<b[^>]*>(.*?)</b>", "html_bold"),
            # Standalone text patterns that look like labels (word/phrase followed by colon)
            (r"\b([A-Z][a-zA-Z\s]+):\s*", "standalone_label"),
        ],
    }

    # File extensions to check
    FILE_EXTENSIONS = {
        ".md": "markdown",
        ".markdown": "markdown",
        ".html": "html",
        ".htm": "html",
        ".jinja": "jinja",
        ".jinja2": "jinja",
    }

    # Words that should remain capitalized (proper nouns, acronyms, etc.)
    ALWAYS_CAPITALIZE = {
        "API",
        "APIs",
        "URL",
        "URLs",
        "HTTP",
        "HTTPS",
        "JSON",
        "XML",
        "HTML",
        "CSS",
        "JS",
        "SQL",
        "REST",
        "RESTful",
        "FastAPI",
        "SQLAlchemy",
        "Jinja2",
        "pytest",
        "GitHub",
        "OAuth",
        "JWT",
        "UUID",
        "UUIDs",
        "CRUD",
        "TDD",
        "LLM",
        "LLMs",
        "AI",
        "MVP",
        "PostgreSQL",
        "SQLite",
        "Docker",
        "Python",
        "JavaScript",
        "TypeScript",
        "POST",
        "GET",
        "PUT",
        "DELETE",
        "PATCH",
        "HEAD",
        "OPTIONS",
        "TRACE",
        "CONNECT",
        "Pact",  # Contract testing framework
    }

    # Exception patterns (regex patterns to ignore)
    IGNORE_PATTERNS = [
        r"title-case-ignore",  # Comment containing this phrase
        r"<!-- title-case-ignore -->",  # HTML comment
        r"{# title-case-ignore #}",  # Jinja comment
        r"# title-case-ignore",  # Markdown comment
    ]

    def __init__(self, fix_mode: bool = False, respect_gitignore: bool = True):
        self.fix_mode = fix_mode
        self.respect_gitignore = respect_gitignore
        self.violations: List[Dict] = []
        self.gitignore_spec = None
        self.git_root = None

        if self.respect_gitignore:
            self._load_gitignore()

    def _find_git_root(self, start_path: Path = None) -> Path:
        """Find the root of the git repository."""
        if start_path is None:
            start_path = Path.cwd()

        current = start_path.resolve()
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent

        # If no .git found, return the starting directory
        return start_path.resolve()

    def _load_gitignore(self):
        """Load gitignore patterns from .gitignore file."""
        if pathspec is None:
            print(
                "Warning: pathspec library not available. Install with: pip install pathspec",
                file=sys.stderr,
            )
            print("Continuing without gitignore support...", file=sys.stderr)
            return

        self.git_root = self._find_git_root()
        gitignore_path = self.git_root / ".gitignore"

        if not gitignore_path.exists():
            return

        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                gitignore_content = f.read()

            self.gitignore_spec = pathspec.PathSpec.from_lines(
                "gitwildmatch", gitignore_content.splitlines()
            )
        except Exception as e:
            print(f"Warning: Could not load .gitignore: {e}", file=sys.stderr)

    def _is_gitignored(self, file_path: Path) -> bool:
        """Check if a file is ignored by gitignore."""
        if (
            not self.respect_gitignore
            or self.gitignore_spec is None
            or self.git_root is None
        ):
            return False

        try:
            # Get relative path from git root
            relative_path = file_path.resolve().relative_to(self.git_root)
            return self.gitignore_spec.match_file(str(relative_path))
        except (ValueError, OSError):
            # File is outside git repository or other error
            return False

    def should_ignore_line(self, line: str) -> bool:
        """Check if a line should be ignored based on exception patterns."""
        for pattern in self.IGNORE_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                return True

        # Ignore lines that are inside CSS style blocks
        if re.search(r"^\s*[a-z-]+\s*:\s*[^;]+;?\s*$", line.strip()):
            return True

        # Ignore lines that are Jinja comments
        if re.search(r"^\s*{#.*#}\s*$", line.strip()):
            return True

        return False

    def should_ignore_file(self, file_path: Path) -> bool:
        """Check if entire file should be ignored based on .titleignore file or gitignore."""
        # Check gitignore first
        if self._is_gitignored(file_path):
            return True

        # Check .titleignore file
        ignore_file = file_path.parent / ".titleignore"
        if ignore_file.exists():
            patterns = ignore_file.read_text().strip().split("\n")
            for pattern in patterns:
                pattern = pattern.strip()
                if pattern and not pattern.startswith("#"):
                    if file_path.match(pattern) or str(file_path).endswith(pattern):
                        return True
        return False

    def is_colon_pattern(self, text: str) -> bool:
        """Check if text follows patterns that should be exempt from sentence case rules.

        Exempt patterns:
        - Document titles like "Something: A detailed explanation"
        - Section headers like "Chapter 1: Introduction"
        - Step-by-step instructions like "Step 1: Consumer test"
        - But NOT simple field labels like "Name:", "Last Activity:", etc.
        """
        # Remove HTML tags for checking
        clean_text = re.sub(r"<[^>]+>", "", text).strip()

        # Check if it contains a colon or dash with text on both sides
        for separator in [":", " - "]:
            if separator in clean_text:
                parts = clean_text.split(separator, 1)
                if len(parts) == 2:
                    before_sep = parts[0].strip()
                    after_sep = parts[1].strip()

                    # If both parts have content, check if this looks like a title pattern
                    if before_sep and after_sep:
                        # Exempt if the part after the separator is substantial (more than just a few words)
                        # This catches "Chapter 1: Introduction to the topic" but not "Name: John"
                        after_words = after_sep.split()
                        if len(after_words) >= 3:  # At least 3 words after separator
                            return True

                        # Also exempt if the before part looks like a chapter/section number
                        if re.match(
                            r"^(Chapter|Section|Part|Book)\s+\d+$",
                            before_sep,
                            re.IGNORECASE,
                        ):
                            return True

                        # Exempt step-by-step instruction patterns like "Step 1: Consumer test"
                        if re.match(r"^Step\s+\d+$", before_sep, re.IGNORECASE):
                            return True

        return False

    def remove_leading_emojis(self, text: str) -> str:
        """Remove leading emojis from text for sentence case checking."""
        # Emoji regex pattern - matches most common emoji ranges
        emoji_pattern = r"^[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002600-\U000027BF\U0001F900-\U0001F9FF\U0001F018-\U0001F270\U0001F000-\U0001F02F\U0001F0A0-\U0001F0FF\U0001F100-\U0001F64F\U0001F170-\U0001F251\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000027BF\U0001F018-\U0001F270\U0001F000-\U0001F02F\U0001F0A0-\U0001F0FF\U0001F100-\U0001F64F\U0001F170-\U0001F251]+\s*"

        # Remove leading emojis and whitespace
        cleaned = re.sub(emoji_pattern, "", text)
        return cleaned

    def convert_to_sentence_case(self, text: str) -> str:
        """Convert text to sentence case, preserving proper nouns and acronyms."""
        # Check if this is a colon pattern that should be exempt
        if self.is_colon_pattern(text):
            return text

        # Remove HTML tags for processing
        clean_text = re.sub(r"<[^>]+>", "", text).strip()

        # If empty after cleaning, return original
        if not clean_text:
            return text

        # Handle emojis at the beginning
        original_clean = clean_text
        clean_text_no_emoji = self.remove_leading_emojis(clean_text)
        emoji_prefix = original_clean[: len(original_clean) - len(clean_text_no_emoji)]

        # Create a lookup map for proper capitalization
        capitalize_map = {word.upper(): word for word in self.ALWAYS_CAPITALIZE}

        words = clean_text_no_emoji.split()
        if not words:
            return text

        result_words = []
        for i, word in enumerate(words):
            # Remove punctuation for checking
            clean_word = re.sub(r"[^\w]", "", word)

            if i == 0:
                # First word: capitalize first letter only, unless it's a special word
                if clean_word.upper() in capitalize_map:
                    proper_case = capitalize_map[clean_word.upper()]
                    result_words.append(word.replace(clean_word, proper_case))
                else:
                    # Capitalize only first letter
                    if clean_word:
                        new_word = word.replace(
                            clean_word, clean_word[0].upper() + clean_word[1:].lower()
                        )
                        result_words.append(new_word)
                    else:
                        result_words.append(word)
            else:
                # Other words: only capitalize if in ALWAYS_CAPITALIZE
                if clean_word.upper() in capitalize_map:
                    proper_case = capitalize_map[clean_word.upper()]
                    result_words.append(word.replace(clean_word, proper_case))
                else:
                    result_words.append(word.replace(clean_word, clean_word.lower()))

        sentence_case = emoji_prefix + " ".join(result_words)

        # If original had HTML tags, try to preserve them
        if "<" in text and ">" in text:
            # Simple approach: replace the clean text in the original
            return text.replace(original_clean, sentence_case)

        return sentence_case

    def is_sentence_case(self, text: str) -> bool:
        """Check if text follows sentence case rules."""
        expected = self.convert_to_sentence_case(text)
        return text == expected

    def _detect_jinja_syntax(self, content: str) -> bool:
        """Detect if content contains Jinja template syntax."""
        jinja_patterns = [
            r"{%.*?%}",  # Jinja blocks like {% block %}, {% for %}, etc.
            r"{{.*?}}",  # Jinja variables like {{ variable }}
            r"{#.*?#}",  # Jinja comments like {# comment #}
        ]

        for pattern in jinja_patterns:
            if re.search(pattern, content, re.DOTALL):
                return True
        return False

    def _get_file_type(self, file_path: Path, content: str = None) -> str:
        """Determine the file type, with special handling for HTML files that contain Jinja syntax."""
        extension = file_path.suffix.lower()
        if extension not in self.FILE_EXTENSIONS:
            return None

        base_type = self.FILE_EXTENSIONS[extension]

        # If it's an HTML file, check if it contains Jinja syntax
        if base_type == "html":
            if content is None:
                try:
                    content = file_path.read_text(encoding="utf-8")
                except Exception:
                    return base_type

            # Check if the file contains Jinja syntax or is in a templates directory
            if (
                self._detect_jinja_syntax(content)
                or "template" in str(file_path).lower()
            ):
                return "jinja"

        return base_type

    def check_file(self, file_path: Path) -> List[Dict]:
        """Check a single file for title case violations."""
        if self.should_ignore_file(file_path):
            return []

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"Error reading {file_path}: {e}", file=sys.stderr)
            return []

        file_type = self._get_file_type(file_path, content)
        if file_type is None:
            return []

        patterns = self.PATTERNS[file_type]
        violations = []

        lines = content.split("\n")
        in_style_block = False
        in_script_block = False

        for line_num, line in enumerate(lines, 1):
            # Track context
            if "<style" in line.lower():
                in_style_block = True
            elif "</style>" in line.lower():
                in_style_block = False
                continue  # Skip the closing style tag line
            elif "<script" in line.lower():
                in_script_block = True
            elif "</script>" in line.lower():
                in_script_block = False
                continue  # Skip the closing script tag line

            # Skip lines in style or script blocks
            if in_style_block or in_script_block:
                continue

            if self.should_ignore_line(line):
                continue

            for pattern, pattern_type in patterns:
                matches = re.finditer(pattern, line, re.IGNORECASE | re.DOTALL)
                for match in matches:
                    if pattern_type == "markdown_header":
                        title_text = match.group(2).strip()
                        header_level = match.group(1)
                    elif pattern_type in ["html_header", "html_header_in_md"]:
                        title_text = match.group(2).strip()
                        header_level = f"h{match.group(1)}"
                    elif pattern_type in ["html_title", "jinja_title_block"]:
                        title_text = match.group(1).strip()
                        header_level = "title"
                    elif pattern_type in ["html_label", "html_button", "html_link"]:
                        title_text = match.group(1).strip()
                        header_level = pattern_type.replace("html_", "")
                    elif pattern_type in ["html_strong", "html_bold"]:
                        title_text = match.group(1).strip()
                        header_level = pattern_type.replace("html_", "")
                        # Skip if this contains Jinja template expressions
                        if self._contains_jinja_expression(title_text):
                            continue
                    elif pattern_type in ["standalone_label"]:
                        title_text = match.group(1).strip()
                        header_level = "label"
                        # Additional filtering for standalone labels
                        if self._is_likely_css_property(
                            title_text
                        ) or self._is_in_comment_context(line):
                            continue
                    else:
                        continue

                    if title_text and not self.is_sentence_case(title_text):
                        violation = {
                            "file": file_path,
                            "line": line_num,
                            "original": title_text,
                            "suggested": self.convert_to_sentence_case(title_text),
                            "pattern_type": pattern_type,
                            "header_level": header_level,
                            "full_line": line,
                        }
                        violations.append(violation)

        return violations

    def _is_likely_css_property(self, text: str) -> bool:
        """Check if text looks like a CSS property name."""
        css_properties = {
            "margin",
            "padding",
            "border",
            "background",
            "color",
            "font",
            "text",
            "display",
            "position",
            "top",
            "bottom",
            "left",
            "right",
            "width",
            "height",
            "max-width",
            "max-height",
            "min-width",
            "min-height",
            "overflow",
            "float",
            "clear",
            "z-index",
            "opacity",
            "visibility",
            "cursor",
            "outline",
            "box-shadow",
            "border-radius",
            "transform",
            "transition",
            "animation",
            "flex",
            "grid",
        }
        return text.lower().replace("-", "").replace(" ", "") in css_properties

    def _is_in_comment_context(self, line: str) -> bool:
        """Check if the line appears to be in a comment context."""
        stripped = line.strip()
        return (
            stripped.startswith("{#")
            or stripped.startswith("<!--")
            or "{#" in line
            and "#}" in line
        )

    def _contains_jinja_expression(self, text: str) -> bool:
        """Check if text contains Jinja template expressions."""
        jinja_patterns = [
            r"{%.*?%}",  # Jinja blocks like {% block %}, {% for %}, etc.
            r"{{.*?}}",  # Jinja variables like {{ variable }}
            r"{#.*?#}",  # Jinja comments like {# comment #}
        ]

        for pattern in jinja_patterns:
            if re.search(pattern, text, re.DOTALL):
                return True
        return False

    def fix_file(self, file_path: Path, violations: List[Dict]) -> bool:
        """Fix title case violations in a file."""
        if not violations:
            return False

        try:
            content = file_path.read_text(encoding="utf-8")

            # Sort violations by line number in reverse order to maintain line positions
            sorted_violations = sorted(
                violations, key=lambda v: v["line"], reverse=True
            )

            lines = content.split("\n")
            for violation in sorted_violations:
                line_idx = violation["line"] - 1
                if 0 <= line_idx < len(lines):
                    lines[line_idx] = lines[line_idx].replace(
                        violation["original"], violation["suggested"]
                    )

            file_path.write_text("\n".join(lines), encoding="utf-8")
            return True

        except Exception as e:
            print(f"Error fixing {file_path}: {e}", file=sys.stderr)
            return False

    def check_directory(self, directory: Path, recursive: bool = True) -> List[Dict]:
        """Check all files in a directory, skipping hidden directories."""
        all_violations = []

        def should_skip_directory(dir_path: Path) -> bool:
            """Check if a directory should be skipped entirely."""
            # Skip hidden directories (starting with '.')
            if dir_path.name.startswith("."):
                return True

            # Skip common build/cache directories
            skip_dirs = {
                "__pycache__",
                "node_modules",
                ".pytest_cache",
                ".mypy_cache",
                ".tox",
                "venv",
                ".venv",
                "env",
                ".env",
                "build",
                "dist",
                ".coverage",
            }
            if dir_path.name in skip_dirs:
                return True

            return False

        def scan_directory(current_dir: Path, is_recursive: bool = True):
            """Recursively scan directory, skipping hidden directories."""
            try:
                for item in current_dir.iterdir():
                    if item.is_file():
                        # Check if file should be processed
                        if not self.should_ignore_file(item):
                            violations = self.check_file(item)
                            all_violations.extend(violations)
                    elif item.is_dir() and is_recursive:
                        # Skip hidden and unwanted directories
                        if not should_skip_directory(item):
                            scan_directory(item, is_recursive)
            except PermissionError:
                # Skip directories we don't have permission to read
                pass
            except Exception as e:
                print(f"Warning: Error scanning {current_dir}: {e}", file=sys.stderr)

        scan_directory(directory, recursive)
        return all_violations

    def run(self, paths: List[Union[str, Path]]) -> int:
        """Run the checker on the given paths."""
        all_violations = []

        for path_str in paths:
            path = Path(path_str)
            if path.is_file():
                violations = self.check_file(path)
                all_violations.extend(violations)
            elif path.is_dir():
                violations = self.check_directory(path)
                all_violations.extend(violations)
            else:
                print(f"Warning: {path} does not exist", file=sys.stderr)

        if not all_violations:
            print("✅ No title case violations found!")
            return 0

        # Group violations by file
        by_file = {}
        for violation in all_violations:
            file_path = violation["file"]
            if file_path not in by_file:
                by_file[file_path] = []
            by_file[file_path].append(violation)

        # Report violations
        total_violations = len(all_violations)
        print(
            f"❌ Found {total_violations} title case violation(s) in {len(by_file)} file(s):"
        )
        print()

        for file_path, violations in by_file.items():
            print(f"📄 {file_path}")
            for violation in violations:
                print(f"  Line {violation['line']:3d}: {violation['header_level']}")
                print(f"    Current:   '{violation['original']}'")
                print(f"    Suggested: '{violation['suggested']}'")
                print()

        if self.fix_mode:
            print("🔧 Fixing violations...")
            fixed_count = 0
            for file_path, violations in by_file.items():
                if self.fix_file(file_path, violations):
                    fixed_count += len(violations)
                    print(f"✅ Fixed {len(violations)} violation(s) in {file_path}")

            print(f"\n✅ Fixed {fixed_count} out of {total_violations} violations")
            return 0 if fixed_count == total_violations else 1
        else:
            print("💡 Run with --fix to automatically correct these violations")
            print("💡 Add 'title-case-ignore' comment to ignore specific lines")
            print("💡 Create .titleignore file to ignore specific files/patterns")
            return 1


def main():
    parser = argparse.ArgumentParser(
        description="Check and fix title case violations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/title_case_check.py                    # Check all files
  python scripts/title_case_check.py --fix              # Auto-fix violations
  python scripts/title_case_check.py templates/         # Check specific directory
  python scripts/title_case_check.py README.md notes/   # Check specific files/dirs

Exception handling:
  - Add 'title-case-ignore' in a comment to ignore specific lines
  - Create .titleignore file with glob patterns to ignore files
  - Use --check-only to report without fixing
  - Use --no-gitignore to disable automatic gitignore support
        """,
    )

    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to check (default: current directory)",
    )

    parser.add_argument(
        "--fix", action="store_true", help="Automatically fix title case violations"
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check for violations, do not fix",
    )

    parser.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Disable automatic gitignore support (check all files)",
    )

    args = parser.parse_args()

    # --check-only overrides --fix
    fix_mode = args.fix and not args.check_only
    respect_gitignore = not args.no_gitignore

    checker = TitleCaseChecker(fix_mode=fix_mode, respect_gitignore=respect_gitignore)
    return checker.run(args.paths)


if __name__ == "__main__":
    sys.exit(main())
