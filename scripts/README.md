# 🔧 Development scripts

This directory contains scripts for maintaining code quality and consistency.

## 📋 Available scripts

### `title_case_check.py`

Enforces sentence case for titles across the codebase, following the project's documentation standards.

#### 🎯 **Quick usage**

```bash
# Check all files for title case violations
python scripts/title_case_check.py

# Auto-fix violations
python scripts/title_case_check.py --fix

# Check specific directory
python scripts/title_case_check.py templates/

# Check specific files
python scripts/title_case_check.py README.md notes/
```

#### 🏗️ **supported file types**

- **Markdown files** (`.md`, `.markdown`): Headers (`# Title`, `## Subtitle`)
- **HTML files** (`.html`, `.htm`): Headers (`<h1>`, `<h2>`, etc.) and `<title>` tags
- **Jinja templates** (`.jinja`, `.jinja2`): HTML headers and `{% block title %}` blocks

#### 📝 **Exception handling**

**Line-level exceptions:**

```markdown
# This Title Will Be Ignored <!-- title-case-ignore -->
```

```html
<h1>API documentation</h1>
<!-- title-case-ignore -->
```
