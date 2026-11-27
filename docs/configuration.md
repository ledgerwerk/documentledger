# Configuration reference

The canonical tool configuration is `.ledger/documentledger/config.toml`, version 2. Project identity and mount routing belong to `.ledger/ledger.toml` and ledgercore, not this file.

<!-- docledger-section: configuration-example -->

## Example

```toml
config_version = 2

[ledger]
code = "dl"

[scan]
source_roots = ["documentledger", "tests"]
doc_roots = ["docs", "README.md"]
source_extensions = [".py"]
doc_extensions = [".md"]

[validation]
commands = [
  "python -m pytest -q",
  "python -m compileall -q documentledger tests",
  "bash docs/build.sh",
]

[policy]
require_doc_frontmatter = false
mapping_review_roles = ["production"]
```

<!-- docledger-section: configuration-fields -->

## Fields

| Field                            | Type and default                     | Normalization and validation                   | Effect                                                       |
| -------------------------------- | ------------------------------------ | ---------------------------------------------- | ------------------------------------------------------------ |
| `config_version`                 | integer, required, `2`               | Must be exactly 2; unknown versions fail       | Selects the tool schema.                                     |
| `ledger.code`                    | non-empty string, default `dl`       | Must be a string                               | Prefix used by project-local ledger conventions.             |
| `scan.source_roots`              | array of strings, default empty      | Paths are interpreted relative to project root | Configured at init; later roots are not added automatically. |
| `scan.doc_roots`                 | array of strings, default empty      | Paths are interpreted relative to project root | Files collected and parsed as documentation.                 |
| `scan.source_extensions`         | array of strings, default empty      | Extension filters are explicit                 | Limits source collection.                                    |
| `scan.doc_extensions`            | array of strings, default empty      | Extension filters are explicit                 | Limits documentation collection.                             |
| `validation.commands`            | array of strings, default empty      | Preserved as ordered commands                  | Commands used by context and `check`.                        |
| `policy.require_doc_frontmatter` | boolean, default `false`             | Non-boolean values fail                        | Requires front matter during validation.                     |
| `policy.mapping_review_roles`    | string array, default ["production"] | Supported role names only                      | Unmapped changes in selected roles require mapping review.   |

## Source-root discovery

`documentledger init` discovers production roots from project metadata, then falls back to a single conventional package or top-level module when metadata does not identify one. Ambiguous package roots require an explicit repeatable `--source-root PATH` selection. The `tests` root is appended only when it already contains Python files at initialization.

Discovery is a one-time initialization decision. The selected roots are written to `scan.source_roots`; later package or test directories do not change the configuration. When `--source-root` is supplied, the explicit list is stored without adding other discovered roots. Edit `scan.source_roots` deliberately to change the indexed roots.

Unknown tables and fields fail with `unsupported_tool_config_field`; wrong types fail with `invalid_tool_config`; unsupported versions fail with `unsupported_tool_config_version`.

The supported source roles are `production`, `test`, `private`, `generated`, `documentation-support`, and `unknown`. The default selects only `production`; opt additional roles in when their changes should require documentation mappings.

<!-- docledger-section: configuration-commands -->

## Inspect and validate

```bash
documentledger config show
documentledger config validate
```

Both commands read the effective canonical configuration. Validation is read-only and does not rewrite malformed files. Legacy root configuration files are migration inputs only, not the normal configuration model.
