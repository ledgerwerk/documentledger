import sys
from importlib import metadata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

project = "documentledger"
copyright = "2026, Documentledger Contributors"
author = "Documentledger Contributors"

try:
    release = metadata.version("documentledger")
except metadata.PackageNotFoundError:
    try:
        import documentledger

        release = documentledger.__version__
    except (ImportError, AttributeError):
        release = "0+unknown"

version = ".".join(release.split(".")[:2])

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",
]

source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
}

root_doc = "index"

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
]

myst_heading_anchors = 4

templates_path = ["_templates"]
exclude_patterns = ["_build", "_build/**", "venv", "venv/**", "api.md", "Thumbs.db", ".DS_Store", ".ledger"]

html_theme = "sphinx_rtd_theme"

autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "show-inheritance": True,
}

autodoc_typehints = "description"
autodoc_class_signature = "separated"
always_document_param_types = True
typehints_fully_qualified = False
autosummary_generate = True
todo_include_todos = False
nitpicky = True

# Keep this list deliberately narrow.  The documentation should surface
# unresolved references rather than hiding broad warning classes.
nitpick_ignore = [
    ("py:class", "typer.models.Context"),
    ("py:class", "ledgercore.cli.model.CommonCLIState"),
    ("py:class", "ledgercore.cli.errors.CLIError"),
    ("py:class", "ledgercore.manifest.LedgerProjectManifest"),
    ("py:class", "ledgercore.cli.errors.ExitCode"),
    ("py:class", "ledgercore.errors.LedgerCoreError"),
    ("py:class", "pathlib.Path"),
    ("py:class", "collections.abc.Mapping"),
    ("py:data", "typing.Any"),
    ("py:data", "typing.Literal"),
    ("py:data", "Ellipsis"),
    ("py:exc", "AssertionError with details if drift is detected."),
]

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
}
