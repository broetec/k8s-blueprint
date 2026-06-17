# =============================================================================
# docs/conf.py — Sphinx configuration
#
# Build: sphinx-build -b html -c docs . docs/_build/html
#        (srcdir = repo root, confdir = docs/)
# Quick: make docs-html
# =============================================================================

project = "k8s-blueprint"
author = "Broetec"
release = "0.1"

# -- Extensions ---------------------------------------------------------------

extensions = ["myst_parser", "sphinxcontrib.mermaid"]

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}

master_doc = "docs/index"

exclude_patterns = [
    "_build",
    ".venv",
    "graphify-out",
    "tests",
    ".git",
    ".cursor",
    "uv.lock",
    "docs/_build",
    ".pytest_cache",
]

# -- MyST configuration -------------------------------------------------------

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "tasklist",
]
myst_fence_as_directive = ["mermaid"]

# -- HTML output --------------------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_title = "k8s-blueprint"
html_static_path = []


def setup(app):
    """Fix Sphinx crash when section headings contain inline links.

    myst-parser creates reference nodes inside section titles for headings like
    `### [text](url)`. These inner reference nodes end up in env.tocs but lack
    the 'anchorname' and 'refuri' attributes that Sphinx expects on every
    reference node in the toc tree.  Both document_toc (page-local TOC) and
    _resolve_toctree (sidebar navigation) crash on the missing attributes.

    Fixing env.tocs at read time (via doctree-read) propagates the fix to all
    downstream consumers without needing to patch multiple private functions.
    """
    from docutils import nodes as _nodes

    def _fix_heading_link_refs(app, doctree):
        docname = app.env.docname
        if docname not in app.env.tocs:
            return
        for node in app.env.tocs[docname].findall(_nodes.reference):
            node.attributes.setdefault('anchorname', '')
            node.attributes.setdefault('refuri', docname)

    app.connect('doctree-read', _fix_heading_link_refs)
