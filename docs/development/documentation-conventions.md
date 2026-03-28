# Documentation Conventions

This guide explains how to keep documentation synchronized with the codebase and avoid disconnected code examples.

## Problem: Disconnected Documentation

Documentation that contains pseudo-code or example snippets that don't match the actual implementation creates several problems:

1. **Misleading users** who try to use the examples
2. **Maintenance burden** when code changes but docs don't
3. **Loss of trust** in documentation accuracy

## Solution: Linked Documentation

We use several techniques to keep documentation synchronized with code.

### 1. Source Code References

Always include links to actual implementation when showing conceptual code:

```markdown
!!! info "Conceptual Logic"
    The following illustrates the logic. For the actual implementation,
    see [`classifier.py:285-392`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/classifier.py#L285-L392).
```

**Format for GitHub links:**
```
https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/classifier.py#L285-L392
```

### 2. Embedded Code Snippets

Use `pymdownx.snippets` to embed actual code from source files.

**Syntax:**

The snippet marker looks like scissors: two dashes, the digit 8, a less-than sign, and two more dashes (`-` `-` `8` `<` `-` `-`), followed by a quoted file path.

| Pattern | Description |
|---------|-------------|
| Marker + `"path/to/file.py"` | Include entire file |
| Marker + `"path/to/file.py:10:50"` | Include lines 10-50 |

Path is relative to repository root. See [pymdownx.snippets docs](https://facelessuser.github.io/pymdown-extensions/extensions/snippets/) for full syntax.

**Example** - the actual snippets in retail.md look like:

??? example "See retail.md for working example"
    ```python
    --8<-- "src/rwa_calc/engine/classifier.py:285:310"
    ```

### 3. Auto-generated API Documentation

Use `mkdocstrings` to generate documentation from docstrings:

```markdown
::: rwa_calc.engine.classifier.ExposureClassifier
    options:
      show_root_heading: true
      members:
        - classify
      show_source: false
```

This automatically pulls docstrings and keeps them in sync with code.

### 4. Admonitions for Pseudo-code

When pseudo-code is necessary for conceptual explanation, mark it clearly:

```markdown
!!! info "Conceptual Logic"
    The following is simplified pseudo-code to illustrate the concept.

```python
# This is conceptual - see actual implementation below
def simplified_example():
    pass
```
```

### 5. Collapsible Actual Code

Use collapsible sections to show lengthy actual code without cluttering the page:

??? example "See this working example from hierarchy.py"
    ```python
    --8<-- "src/rwa_calc/engine/hierarchy.py:60:100"
    ```

## Best Practices

### When Writing New Documentation

1. **Start with the actual code** - Read the implementation first
2. **Use mkdocstrings for API docs** - Let docstrings be the source of truth
3. **Link, don't copy** - Use snippets rather than copying code
4. **Mark pseudo-code clearly** - Use admonitions to indicate conceptual code

### When Updating Code

1. **Check for documentation** - Search for references to your function/class
2. **Update line numbers** - Snippet references may need adjustment
3. **Update docstrings** - mkdocstrings will pull these automatically
4. **Run docs locally** - `zensical serve` to verify everything renders

### Documentation Structure

| Documentation Type | Approach |
|-------------------|----------|
| API Reference | Use `::: module.Class` for auto-generation |
| Conceptual Guides | Pseudo-code with source links |
| Tutorials | Embedded snippets from actual code |
| Examples | Working code from test files |

## Available Tools

### pymdownx.snippets

Configuration in `zensical.toml`:
```toml
[project.markdown_extensions.pymdownx.snippets]
base_path = ["."]
check_paths = false
```

### mkdocstrings

Configuration in `zensical.toml`:
```toml
[project.plugins.mkdocstrings.handlers.python.options]
docstring_style = "google"
show_source = true
show_root_heading = true
members_order = "source"
```

### Admonitions

Available types: `note`, `info`, `tip`, `warning`, `danger`, `example`

## Checking Documentation

Before submitting changes:

1. Run `zensical serve` locally
2. Check that snippets render correctly
3. Verify GitHub links point to correct lines
4. Ensure mkdocstrings generates expected output

## Migration Checklist

When finding disconnected code in documentation:

- [ ] Identify the actual implementation
- [ ] Add source code reference link
- [ ] Convert to embedded snippet if appropriate
- [ ] Add admonition if keeping conceptual code
- [ ] Update line references after code changes
