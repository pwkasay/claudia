"""
Documentation Agent for Claudia.

Generates human-centered documentation about codebase architecture,
development workflows, and APIs. Designed to be concise and actionable,
not verbose AI-speak.

Usage:
    from claudia.docs import DocsAgent

    agent = DocsAgent()
    agent.analyze()
    agent.generate('architecture')
"""

import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Python 3.10+ provides stdlib_module_names
# Fallback for earlier versions (though project requires 3.10+)
try:
    STDLIB_MODULES = frozenset(sys.stdlib_module_names)
except AttributeError:
    # Minimal fallback list for common stdlib modules
    STDLIB_MODULES = frozenset({
        'abc', 'argparse', 'ast', 'asyncio', 'base64', 'collections',
        'contextlib', 'copy', 'dataclasses', 'datetime', 'enum', 'functools',
        'glob', 'hashlib', 'http', 'importlib', 'inspect', 'io', 'itertools',
        'json', 'logging', 'math', 'os', 'pathlib', 'pickle', 'platform',
        're', 'shutil', 'signal', 'socket', 'sqlite3', 'ssl', 'string',
        'subprocess', 'sys', 'tempfile', 'threading', 'time', 'traceback',
        'typing', 'unittest', 'urllib', 'uuid', 'warnings', 'xml', 'zipfile',
    })


@dataclass
class ProjectMetadata:
    """Project metadata from pyproject.toml, setup.py, or package.json."""
    name: str = ""
    version: str = ""
    description: str = ""
    authors: list = field(default_factory=list)
    license: str = ""
    homepage: str = ""
    repository: str = ""
    python_requires: str = ""
    keywords: list = field(default_factory=list)


@dataclass
class FileInfo:
    """Information about a source file."""
    path: str
    size: int
    lines: int
    language: str
    imports: list = field(default_factory=list)
    exports: list = field(default_factory=list)
    functions: list = field(default_factory=list)
    classes: list = field(default_factory=list)
    methods: dict = field(default_factory=dict)  # {class_name: [method_names]}
    description: str = ""
    class_docstrings: dict = field(default_factory=dict)  # {class_name: docstring}
    function_docstrings: dict = field(default_factory=dict)  # {function_name: docstring}
    signatures: dict = field(default_factory=dict)  # {function_name: {params, return_type}}


@dataclass
class LanguageConfig:
    """Configuration for language-specific code analysis.

    Provides regex patterns for extracting symbols from source files.
    Used by the universal symbol extractor to support multiple languages.
    """
    extensions: tuple
    class_pattern: str = None  # Regex to match class/struct/type definitions
    function_pattern: str = None  # Regex to match function definitions
    import_pattern: str = None  # Regex to match import statements
    export_pattern: str = None  # Regex to match exports (for JS/TS)
    comment_single: str = '//'  # Single-line comment prefix
    comment_multi: tuple = ('/*', '*/')  # Multi-line comment delimiters
    private_prefix: str = '_'  # Prefix for private symbols (Python convention)


# Language configurations for universal symbol extraction
LANGUAGE_CONFIGS = {
    'python': LanguageConfig(
        extensions=('.py',),
        class_pattern=r'^class\s+(\w+)',
        function_pattern=r'^def\s+(\w+)\s*\(',
        import_pattern=r'^(?:from\s+(\S+)\s+import|import\s+(\S+))',
        comment_single='#',
        comment_multi=('"""', '"""'),
        private_prefix='_',
    ),
    'javascript': LanguageConfig(
        extensions=('.js', '.jsx', '.mjs', '.cjs'),
        class_pattern=r'^(?:export\s+)?class\s+(\w+)',
        function_pattern=r'^(?:export\s+)?(?:async\s+)?function\s+(\w+)',
        # Matches ES6 imports AND CommonJS require()
        import_pattern=r'^import\s+.*from\s+[\'"]([^\'"]+)[\'"]|require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
        export_pattern=r'^export\s+(?:default\s+)?(?:const|let|var|function|class)\s+(\w+)',
        private_prefix='_',
    ),
    'typescript': LanguageConfig(
        extensions=('.ts', '.tsx'),
        class_pattern=r'^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)',
        function_pattern=r'^(?:export\s+)?(?:async\s+)?function\s+(\w+)',
        import_pattern=r'^import\s+.*from\s+[\'"]([^\'"]+)[\'"]',
        export_pattern=r'^export\s+(?:default\s+)?(?:const|let|var|function|class|interface|type)\s+(\w+)',
        private_prefix='_',
    ),
    'go': LanguageConfig(
        extensions=('.go',),
        class_pattern=r'^type\s+(\w+)\s+struct\s*\{',
        function_pattern=r'^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(',
        import_pattern=r'^\s*"([^"]+)"',  # Inside import block
        comment_single='//',
        private_prefix='',  # Go uses capitalization for visibility
    ),
    'rust': LanguageConfig(
        extensions=('.rs',),
        class_pattern=r'^(?:pub\s+)?(?:struct|enum|trait)\s+(\w+)',
        function_pattern=r'^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)',
        import_pattern=r'^use\s+([^;{]+)',
        comment_single='//',
        private_prefix='',  # Rust uses pub for visibility
    ),
    'java': LanguageConfig(
        extensions=('.java',),
        class_pattern=r'^(?:public\s+)?(?:abstract\s+)?(?:final\s+)?class\s+(\w+)',
        function_pattern=r'^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+)?\s*\{',
        import_pattern=r'^import\s+([\w.]+);',
        comment_single='//',
        private_prefix='',  # Java uses access modifiers
    ),
    'ruby': LanguageConfig(
        extensions=('.rb',),
        class_pattern=r'^class\s+(\w+)',
        function_pattern=r'^def\s+(\w+)',
        import_pattern=r'^require\s+[\'"]([^\'"]+)[\'"]',
        comment_single='#',
        private_prefix='_',
    ),
    'kotlin': LanguageConfig(
        extensions=('.kt', '.kts'),
        class_pattern=r'^(?:data\s+)?(?:sealed\s+)?class\s+(\w+)',
        function_pattern=r'^(?:suspend\s+)?fun\s+(\w+)',
        import_pattern=r'^import\s+([\w.]+)',
        comment_single='//',
        private_prefix='_',
    ),
    'swift': LanguageConfig(
        extensions=('.swift',),
        class_pattern=r'^(?:public\s+)?(?:final\s+)?(?:class|struct|enum|protocol)\s+(\w+)',
        function_pattern=r'^(?:public\s+)?(?:static\s+)?func\s+(\w+)',
        import_pattern=r'^import\s+(\w+)',
        comment_single='//',
        private_prefix='_',
    ),
    'c': LanguageConfig(
        extensions=('.c', '.h'),
        class_pattern=r'^(?:typedef\s+)?struct\s+(\w+)',
        function_pattern=r'^(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*\{',
        import_pattern=r'^#include\s*[<"]([^>"]+)[>"]',
        comment_single='//',
        private_prefix='_',
    ),
    'cpp': LanguageConfig(
        extensions=('.cpp', '.hpp', '.cc', '.cxx', '.hxx'),
        class_pattern=r'^(?:template\s*<[^>]+>\s*)?class\s+(\w+)',
        function_pattern=r'^(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*(?:const)?\s*(?:override)?\s*\{',
        import_pattern=r'^#include\s*[<"]([^>"]+)[>"]',
        comment_single='//',
        private_prefix='_',
    ),
}


@dataclass
class ProjectType:
    """Detected project type and characteristics.

    Used to generate appropriate documentation based on what kind
    of project this is (CLI, library, web app, API, etc.).

    Supports hybrid projects (e.g., Flask + Click = API + CLI) via
    the secondary_types field.
    """
    primary: str  # cli, library, webapp, api, microservice
    framework: str = ''  # Detected framework (Flask, FastAPI, React, etc.)
    build_system: str = ''  # pip, npm, cargo, go mod, maven, etc.
    confidence: float = 0.0  # 0.0 to 1.0
    characteristics: list = field(default_factory=list)  # Additional traits
    secondary_types: list = field(default_factory=list)  # Other detected types (hybrid projects)


@dataclass
class DocsAgent:
    """
    Documentation generator that analyzes codebases and produces
    human-centered documentation.
    """

    # Extraction limits (class constants)
    MAX_IMPORTS = 20
    MAX_FUNCTIONS = 30
    MAX_CLASSES = 20
    MAX_METHODS_PER_CLASS = 20
    MAX_EXPORTS = 20
    MAX_KEY_CONCEPTS = 15
    MAX_DEPENDENCIES = 20

    project_dir: Path = None
    output_dir: Path = None
    state_file: Path = None

    # Analysis results
    files: dict = field(default_factory=dict)
    structure: dict = field(default_factory=dict)
    entry_points: list = field(default_factory=list)
    key_concepts: list = field(default_factory=list)
    metadata: ProjectMetadata = None

    # Skill level for documentation detail
    skill_level: str = 'mid'  # junior, mid, senior

    # Valid skill levels
    VALID_SKILL_LEVELS = ('junior', 'mid', 'senior')

    def __post_init__(self):
        if self.project_dir is None:
            self.project_dir = Path('.')
        else:
            self.project_dir = Path(self.project_dir)

        if self.output_dir is None:
            self.output_dir = self.project_dir / 'docs'

        if self.state_file is None:
            self.state_file = self.project_dir / '.agent-state' / 'docs-state.json'

        # Validate skill_level
        if self.skill_level not in self.VALID_SKILL_LEVELS:
            raise ValueError(
                f"Invalid skill_level '{self.skill_level}'. "
                f"Must be one of: {', '.join(self.VALID_SKILL_LEVELS)}"
            )

        # Load project metadata on init
        if self.metadata is None:
            self.metadata = self._load_project_metadata()

    # ========================================================================
    # Skill Level Helpers
    # ========================================================================

    def _level_limit(self, items: list, junior: int = 999, mid: int = 5, senior: int = 3) -> list:
        """Return items sliced based on skill level.

        Args:
            items: List to slice
            junior: Max items for junior level (default: all)
            mid: Max items for mid level (default: 5)
            senior: Max items for senior level (default: 3)

        Returns:
            Sliced list appropriate for current skill level
        """
        limits = {'junior': junior, 'mid': mid, 'senior': senior}
        limit = limits.get(self.skill_level, mid)
        return items[:limit] if limit < 999 else items

    def _level_content(self, junior: str = '', mid: str = '', senior: str = '') -> str:
        """Return content appropriate for current skill level.

        Args:
            junior: Content for junior level
            mid: Content for mid level
            senior: Content for senior level

        Returns:
            Content string for current skill level
        """
        content = {'junior': junior, 'mid': mid, 'senior': senior}
        return content.get(self.skill_level, mid)

    def _is_level(self, *levels: str) -> bool:
        """Check if current skill level matches any of the given levels.

        Args:
            *levels: Level names to check against

        Returns:
            True if current level matches any given level
        """
        return self.skill_level in levels

    # ========================================================================
    # Project Metadata Loading
    # ========================================================================

    def _load_project_metadata(self) -> ProjectMetadata:
        """Load project metadata from pyproject.toml, setup.py, or package.json.

        Tries sources in order of preference:
        1. pyproject.toml (modern Python standard)
        2. setup.py (legacy Python)
        3. package.json (JavaScript/TypeScript)

        Returns:
            ProjectMetadata with fields populated from first available source
        """
        # Try pyproject.toml first (modern Python projects)
        pyproject_path = self.project_dir / 'pyproject.toml'
        if pyproject_path.exists():
            try:
                content = pyproject_path.read_text()
                return self._parse_pyproject_toml(content)
            except Exception:
                pass

        # Try setup.py for legacy projects
        setup_py_path = self.project_dir / 'setup.py'
        if setup_py_path.exists():
            try:
                content = setup_py_path.read_text()
                return self._parse_setup_py(content)
            except Exception:
                pass

        # Try package.json for JS/TS projects
        package_json_path = self.project_dir / 'package.json'
        if package_json_path.exists():
            try:
                content = package_json_path.read_text()
                return self._parse_package_json(content)
            except Exception:
                pass

        # Return empty metadata if nothing found
        return ProjectMetadata(name=self.project_dir.resolve().name)

    def _parse_pyproject_toml(self, content: str) -> ProjectMetadata:
        """Parse pyproject.toml for project metadata.

        Uses tomllib (Python 3.11+) if available, otherwise falls back
        to regex extraction for common fields.
        """
        metadata = ProjectMetadata()

        # Try using tomllib first (Python 3.11+)
        try:
            import tomllib
            data = tomllib.loads(content)

            # PEP 621 project table
            project = data.get('project', {})
            metadata.name = project.get('name', '')
            metadata.version = project.get('version', '')
            metadata.description = project.get('description', '')
            metadata.license = project.get('license', {}).get('text', '') if isinstance(project.get('license'), dict) else project.get('license', '')
            metadata.python_requires = project.get('requires-python', '')
            metadata.keywords = project.get('keywords', [])

            # Authors can be list of dicts with 'name' and 'email'
            authors = project.get('authors', [])
            metadata.authors = [a.get('name', '') for a in authors if isinstance(a, dict)]

            # URLs
            urls = project.get('urls', {})
            metadata.homepage = urls.get('Homepage', urls.get('homepage', ''))
            metadata.repository = urls.get('Repository', urls.get('repository', urls.get('Source', '')))

            # Check tool.poetry for Poetry projects
            if not metadata.name and 'tool' in data and 'poetry' in data['tool']:
                poetry = data['tool']['poetry']
                metadata.name = poetry.get('name', '')
                metadata.version = poetry.get('version', '')
                metadata.description = poetry.get('description', '')
                metadata.authors = poetry.get('authors', [])
                metadata.license = poetry.get('license', '')
                metadata.homepage = poetry.get('homepage', '')
                metadata.repository = poetry.get('repository', '')

            return metadata

        except ImportError:
            pass  # Fall through to regex parsing

        # Regex fallback for Python < 3.11
        def extract_toml_value(key: str, section: str = 'project') -> str:
            # Match key = "value" or key = 'value' within section
            pattern = rf'\[{section}\][^\[]*?{key}\s*=\s*["\']([^"\']+)["\']'
            match = re.search(pattern, content, re.DOTALL)
            return match.group(1) if match else ''

        metadata.name = extract_toml_value('name')
        metadata.version = extract_toml_value('version')
        metadata.description = extract_toml_value('description')
        metadata.python_requires = extract_toml_value('requires-python')

        # Try extracting license
        license_match = re.search(r'\[project\][^\[]*license\s*=\s*(?:\{[^}]*text\s*=\s*)?["\']([^"\']+)["\']', content, re.DOTALL)
        if license_match:
            metadata.license = license_match.group(1)

        # Try extracting repository URL
        repo_match = re.search(r'[Rr]epository["\']?\s*=\s*["\']([^"\']+)["\']', content)
        if repo_match:
            metadata.repository = repo_match.group(1)

        # Fallback to folder name if name not found
        if not metadata.name:
            metadata.name = self.project_dir.resolve().name

        return metadata

    def _parse_setup_py(self, content: str) -> ProjectMetadata:
        """Parse setup.py for project metadata using regex extraction."""
        metadata = ProjectMetadata()

        def extract_value(key: str) -> str:
            # Match name="value" or name='value' in setup() call
            pattern = rf'{key}\s*=\s*["\']([^"\']+)["\']'
            match = re.search(pattern, content)
            return match.group(1) if match else ''

        metadata.name = extract_value('name')
        metadata.version = extract_value('version')
        metadata.description = extract_value('description')
        metadata.license = extract_value('license')
        metadata.python_requires = extract_value('python_requires')

        # Extract URL
        url = extract_value('url')
        if url:
            if 'github' in url.lower():
                metadata.repository = url
            else:
                metadata.homepage = url

        # Fallback to folder name if name not found
        if not metadata.name:
            metadata.name = self.project_dir.resolve().name

        return metadata

    def _parse_package_json(self, content: str) -> ProjectMetadata:
        """Parse package.json for project metadata."""
        metadata = ProjectMetadata()

        try:
            data = json.loads(content)
            metadata.name = data.get('name', '')
            metadata.version = data.get('version', '')
            metadata.description = data.get('description', '')
            metadata.license = data.get('license', '')
            metadata.homepage = data.get('homepage', '')

            # Repository can be string or object
            repo = data.get('repository', '')
            if isinstance(repo, dict):
                metadata.repository = repo.get('url', '')
            else:
                metadata.repository = repo

            # Authors - can be string or object
            author = data.get('author', '')
            if isinstance(author, dict):
                metadata.authors = [author.get('name', '')]
            elif author:
                metadata.authors = [author]

            # Keywords
            metadata.keywords = data.get('keywords', [])

        except json.JSONDecodeError:
            pass

        # Fallback to folder name
        if not metadata.name:
            metadata.name = self.project_dir.resolve().name

        return metadata

    # ========================================================================
    # Analysis
    # ========================================================================

    def analyze(self, verbose: bool = False, force: bool = False) -> dict:
        """
        Analyze the codebase structure with incremental support.

        Uses cached analysis for unchanged files to speed up repeated runs.
        A file is considered unchanged if its size matches the cached value.

        Args:
            verbose: Print each file as it's analyzed
            force: If True, re-analyze all files even if cached

        Returns:
            Summary dict including files_analyzed, files_cached, total_lines, etc.
        """
        self.files = {}
        self.structure = {
            'directories': {},
            'file_types': {},
            'total_lines': 0,
        }
        self.entry_points = []
        self.key_concepts = []

        # Load cached state for incremental analysis
        cached_state = None if force else self._load_state()
        cached_hashes = cached_state.get('file_hashes', {}) if cached_state else {}
        cached_file_data = cached_state.get('file_data', {}) if cached_state else {}

        # Track stats
        files_analyzed = 0
        files_cached = 0
        files_removed = 0

        # Find all source files
        source_patterns = [
            '**/*.py', '**/*.js', '**/*.ts', '**/*.jsx', '**/*.tsx',
            '**/*.go', '**/*.rs', '**/*.java', '**/*.rb',
            '**/*.c', '**/*.cpp', '**/*.h', '**/*.hpp',
        ]

        ignore_patterns = [
            '**/node_modules/**', '**/.git/**', '**/venv/**', '**/__pycache__/**',
            '**/dist/**', '**/build/**', '**/.next/**', '**/target/**',
        ]

        current_files = set()

        for pattern in source_patterns:
            for file_path in self.project_dir.glob(pattern):
                # Skip ignored paths
                rel_path = str(file_path.relative_to(self.project_dir))
                if any(self._match_pattern(rel_path, p) for p in ignore_patterns):
                    continue

                current_files.add(rel_path)

                # Check if file is unchanged (same size)
                try:
                    stat = file_path.stat()
                    if rel_path in cached_hashes and rel_path in cached_file_data:
                        cached_size = cached_file_data[rel_path].get('size', -1)
                        if stat.st_size == cached_size:
                            # Size matches, restore from cache
                            info = self._restore_file_info(cached_file_data[rel_path])
                            self.files[rel_path] = info
                            files_cached += 1
                            if verbose:
                                print(f"  Cached: {rel_path}")
                            continue
                except OSError:
                    pass

                # Analyze the file (new or changed)
                info = self._analyze_file(file_path)
                if info:
                    self.files[rel_path] = info
                    files_analyzed += 1
                    if verbose:
                        print(f"  Analyzed: {rel_path}")

        # Count removed files (were in cache but no longer exist)
        if cached_hashes:
            files_removed = len(set(cached_hashes.keys()) - current_files)

        # Build structure summary
        self._build_structure()

        # Find entry points
        self._find_entry_points()

        # Extract key concepts
        self._extract_key_concepts()

        # Save state
        self._save_state()

        return {
            'files_analyzed': files_analyzed,
            'files_cached': files_cached,
            'files_removed': files_removed,
            'total_files': len(self.files),
            'total_lines': self.structure['total_lines'],
            'directories': len(self.structure['directories']),
            'entry_points': len(self.entry_points),
            'key_concepts': len(self.key_concepts),
        }

    def _match_pattern(self, path: str, pattern: str) -> bool:
        """Simple glob-style pattern matching."""
        return fnmatch.fnmatch(path, pattern)

    def _analyze_file(self, file_path: Path) -> Optional[FileInfo]:
        """Analyze a single source file."""
        try:
            content = file_path.read_text(errors='ignore')
            lines = content.split('\n')

            info = FileInfo(
                path=str(file_path.relative_to(self.project_dir)),
                size=file_path.stat().st_size,
                lines=len(lines),
                language=self._detect_language(file_path),
            )

            # Extract based on language
            if info.language == 'python':
                info.imports = self._extract_python_imports(content)
                info.functions = self._extract_python_functions(content)
                info.classes = self._extract_python_classes(content)
                info.methods = self._extract_python_class_methods(content)
                info.description = self._extract_python_docstring(content)
                # Extract docstrings for classes and functions
                class_docs, func_docs = self._extract_python_entity_docstrings(content)
                info.class_docstrings = class_docs
                info.function_docstrings = func_docs
                # Extract function signatures with type hints
                info.signatures = self._extract_python_signatures(content)
            elif info.language in ('javascript', 'typescript'):
                info.imports = self._extract_js_imports(content)
                info.exports = self._extract_js_exports(content)
                info.functions = self._extract_js_functions(content)
                info.classes = self._extract_js_classes(content)
            elif info.language in LANGUAGE_CONFIGS:
                # Use universal extraction for other supported languages
                symbols = self._extract_symbols_universal(content, info.language)
                info.classes = symbols.get('classes', [])
                info.functions = symbols.get('functions', [])
                info.imports = symbols.get('imports', [])
                info.exports = symbols.get('exports', [])

            return info
        except Exception:
            return None

    def _detect_language(self, file_path: Path) -> str:
        """Detect programming language from file extension."""
        ext_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.jsx': 'javascript',
            '.tsx': 'typescript',
            '.mjs': 'javascript',
            '.go': 'go',
            '.rs': 'rust',
            '.java': 'java',
            '.rb': 'ruby',
            '.kt': 'kotlin',
            '.kts': 'kotlin',
            '.swift': 'swift',
            '.c': 'c',
            '.cpp': 'cpp',
            '.cc': 'cpp',
            '.cxx': 'cpp',
            '.h': 'c',
            '.hpp': 'cpp',
            '.hxx': 'cpp',
        }
        return ext_map.get(file_path.suffix.lower(), 'unknown')

    def _extract_symbols_universal(self, content: str, language: str) -> dict:
        """Extract symbols using language-agnostic patterns.

        Uses the LanguageConfig regex patterns to extract classes, functions,
        imports, and exports from source code in any supported language.

        Args:
            content: Source code content
            language: Language name (must be in LANGUAGE_CONFIGS)

        Returns:
            dict with 'classes', 'functions', 'imports', 'exports' lists
        """
        symbols = {
            'classes': [],
            'functions': [],
            'imports': [],
            'exports': [],
        }

        config = LANGUAGE_CONFIGS.get(language)
        if not config:
            return symbols

        # Extract classes/structs/types
        if config.class_pattern:
            for match in re.finditer(config.class_pattern, content, re.MULTILINE):
                name = match.group(1)
                if name and name not in symbols['classes']:
                    symbols['classes'].append(name)
            symbols['classes'] = symbols['classes'][:self.MAX_CLASSES]

        # Extract functions
        if config.function_pattern:
            for match in re.finditer(config.function_pattern, content, re.MULTILINE):
                name = match.group(1)
                if not name:
                    continue
                # Skip private symbols based on language conventions
                if config.private_prefix and name.startswith(config.private_prefix):
                    continue
                # For Go, skip lowercase (unexported) functions
                if language == 'go' and name[0].islower():
                    continue
                if name not in symbols['functions']:
                    symbols['functions'].append(name)
            symbols['functions'] = symbols['functions'][:self.MAX_FUNCTIONS]

        # Extract imports
        if config.import_pattern:
            for match in re.finditer(config.import_pattern, content, re.MULTILINE):
                # Handle patterns with multiple groups
                module = None
                for i in range(1, match.lastindex + 1 if match.lastindex else 2):
                    try:
                        if match.group(i):
                            module = match.group(i).strip()
                            break
                    except IndexError:
                        break
                if module and module not in symbols['imports']:
                    symbols['imports'].append(module)
            symbols['imports'] = symbols['imports'][:self.MAX_IMPORTS]

        # Extract exports (for JS/TS)
        if config.export_pattern:
            for match in re.finditer(config.export_pattern, content, re.MULTILINE):
                name = match.group(1)
                if name and name not in symbols['exports']:
                    symbols['exports'].append(name)
            symbols['exports'] = symbols['exports'][:self.MAX_EXPORTS]

        return symbols

    def _extract_python_imports(self, content: str, include_stdlib: bool = False) -> list:
        """Extract Python imports.

        Args:
            content: Python source code to analyze
            include_stdlib: If False (default), filters out standard library modules

        Returns:
            List of top-level module names, excluding stdlib unless requested
        """
        imports = []
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('import ') or line.startswith('from '):
                # Extract module name
                match = re.match(r'^(?:from\s+(\S+)|import\s+(\S+))', line)
                if match:
                    module = match.group(1) or match.group(2)
                    module = module.split('.')[0]  # Top-level module
                    if module and module not in imports:
                        # Filter stdlib unless explicitly requested
                        if include_stdlib or module not in STDLIB_MODULES:
                            imports.append(module)
        return imports[:self.MAX_IMPORTS]

    def _extract_python_functions(self, content: str) -> list:
        """Extract Python function names."""
        functions = []
        for match in re.finditer(r'^def\s+(\w+)\s*\(', content, re.MULTILINE):
            name = match.group(1)
            if not name.startswith('_') or name.startswith('__'):
                functions.append(name)
        return functions[:self.MAX_FUNCTIONS]

    def _extract_python_signatures(self, content: str) -> dict:
        """Extract Python function signatures with type hints.

        Returns:
            dict: {function_name: {'params': [...], 'return_type': str or None}}
            Each param is {'name': str, 'type': str or None, 'default': str or None}
        """
        signatures = {}

        # Pattern to match function definition with optional return type
        func_pattern = re.compile(
            r'^def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^:]+))?\s*:',
            re.MULTILINE
        )

        for match in func_pattern.finditer(content):
            name = match.group(1)
            params_str = match.group(2).strip()
            return_type = match.group(3).strip() if match.group(3) else None

            # Parse parameters
            params = []
            if params_str:
                # Split on commas, handling nested brackets
                depth = 0
                current = []
                for char in params_str + ',':
                    if char in '([{':
                        depth += 1
                        current.append(char)
                    elif char in ')]}':
                        depth -= 1
                        current.append(char)
                    elif char == ',' and depth == 0:
                        param = ''.join(current).strip()
                        if param:
                            params.append(self._parse_python_param(param))
                        current = []
                    else:
                        current.append(char)

            signatures[name] = {
                'params': params,
                'return_type': return_type,
            }

        return signatures

    def _parse_python_param(self, param: str) -> dict:
        """Parse a single Python parameter into name, type, and default."""
        result = {'name': '', 'type': None, 'default': None}

        # Handle *args and **kwargs
        if param.startswith('**'):
            rest = param[2:]
            result['name'] = '**' + rest.split(':')[0].split('=')[0].strip()
            if ':' in rest:
                result['type'] = rest.split(':', 1)[1].strip()
        elif param.startswith('*'):
            rest = param[1:]
            result['name'] = '*' + rest.split(':')[0].split('=')[0].strip()
            if ':' in rest:
                result['type'] = rest.split(':', 1)[1].strip()
        else:
            # Check for default value first
            if '=' in param:
                param_part, default = param.split('=', 1)
                result['default'] = default.strip()
                param = param_part.strip()

            # Check for type annotation
            if ':' in param:
                name_part, type_part = param.split(':', 1)
                result['name'] = name_part.strip()
                result['type'] = type_part.strip()
            else:
                result['name'] = param.strip()

        return result

    def _extract_python_classes(self, content: str) -> list:
        """Extract Python class names."""
        classes = []
        for match in re.finditer(r'^class\s+(\w+)', content, re.MULTILINE):
            classes.append(match.group(1))
        return classes[:self.MAX_CLASSES]

    def _extract_python_class_methods(self, content: str) -> dict:
        """Extract methods for each class by tracking indentation.

        Python methods are `def` statements that are indented under a `class` block.
        This tracks class/method ownership by monitoring indentation levels.

        Returns:
            dict: {class_name: [method_names]} mapping classes to their methods
        """
        methods = {}
        current_class = None
        class_indent = 0
        lines = content.split('\n')

        for line in lines:
            # Skip empty lines and comments
            stripped = line.lstrip()
            if not stripped or stripped.startswith('#'):
                continue

            indent = len(line) - len(stripped)

            # Check for class definition (must be at column 0 or less indented than current)
            class_match = re.match(r'^class\s+(\w+)', stripped)
            if class_match and (current_class is None or indent <= class_indent):
                current_class = class_match.group(1)
                class_indent = indent
                methods[current_class] = []
                continue

            # Check for method definition (indented under current class)
            if current_class and indent > class_indent:
                method_match = re.match(r'^def\s+(\w+)\s*\(', stripped)
                if method_match:
                    method_name = method_match.group(1)
                    # Include public methods and special methods, skip private helpers
                    if not method_name.startswith('_') or method_name.startswith('__'):
                        methods[current_class].append(method_name)
            elif indent <= class_indent and current_class:
                # We've exited the class block
                current_class = None

        # Limit methods per class
        return {cls: meths[:self.MAX_METHODS_PER_CLASS] for cls, meths in methods.items()}

    def _extract_python_entity_docstrings(self, content: str) -> tuple:
        """Extract docstrings for classes and functions.

        Finds the first triple-quoted string after class/function definitions.

        Returns:
            tuple: (class_docstrings, function_docstrings) dicts mapping names to docstrings
        """
        class_docstrings = {}
        function_docstrings = {}

        # Pattern to match class/function definition followed by docstring
        # Captures: 1=def/class, 2=name, 3=docstring content
        pattern = r'^(class|def)\s+(\w+)[^:]*:\s*\n\s*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')'

        for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
            entity_type = match.group(1)
            name = match.group(2)
            # Docstring is in group 3 (double quotes) or group 4 (single quotes)
            docstring = (match.group(3) or match.group(4) or '').strip()

            if docstring:
                # Clean up and truncate
                docstring = re.sub(r'\n\s*\n', '\n\n', docstring)  # Normalize paragraphs
                docstring = re.sub(r'[ \t]+', ' ', docstring)  # Collapse whitespace
                docstring = self._smart_truncate(docstring, max_length=150)

                if entity_type == 'class':
                    class_docstrings[name] = docstring
                else:
                    # Only include public functions (not private helpers)
                    if not name.startswith('_') or name.startswith('__'):
                        function_docstrings[name] = docstring

        return class_docstrings, function_docstrings

    def _smart_truncate(self, text: str, max_length: int = 200) -> str:
        """Truncate text at sentence boundaries, not mid-word.

        Looks for sentence-ending punctuation (. ! ?) before max_length,
        falls back to word boundary with '...' if none found.
        """
        if len(text) <= max_length:
            return text

        # Look for sentence boundary (. ! ?) followed by space or end
        truncated = text[:max_length]

        # Find last sentence boundary
        sentence_end = -1
        for i in range(len(truncated) - 1, 0, -1):
            if truncated[i] in '.!?' and (i == len(truncated) - 1 or truncated[i + 1] in ' \n'):
                sentence_end = i + 1
                break

        if sentence_end > max_length // 2:  # Only use if we keep at least half
            return truncated[:sentence_end].strip()

        # Fall back to word boundary
        last_space = truncated.rfind(' ')
        if last_space > max_length // 2:
            return truncated[:last_space].strip() + '...'

        # Last resort: hard truncate with ellipsis
        return truncated.strip() + '...'

    def _extract_python_docstring(self, content: str) -> str:
        """Extract module docstring.

        Handles both triple-double-quote and triple-single-quote docstrings.
        Uses smart truncation to avoid cutting off mid-word or mid-sentence.
        """
        # Try triple double quotes first, then triple single quotes
        patterns = [
            r'^[\s]*"""(.*?)"""',   # Triple double quotes
            r"^[\s]*'''(.*?)'''",   # Triple single quotes
        ]

        for pattern in patterns:
            match = re.match(pattern, content, re.DOTALL)
            if match:
                docstring = match.group(1).strip()
                # Clean up internal whitespace while preserving structure
                docstring = re.sub(r'\n\s*\n', '\n\n', docstring)  # Normalize paragraph breaks
                docstring = re.sub(r'[ \t]+', ' ', docstring)  # Collapse horizontal whitespace
                return self._smart_truncate(docstring)

        return ""

    def _extract_js_imports(self, content: str) -> list:
        """Extract JavaScript/TypeScript imports.

        Handles:
        - ES6: import X from 'module' / import { X } from 'module'
        - CommonJS: require('module') / const X = require('module')
        """
        imports = []
        # ES6: import ... from 'module'
        for match in re.finditer(r"import\s+.*?from\s+['\"]([^'\"]+)['\"]", content):
            module = match.group(1)
            if not module.startswith('.'):
                module = module.split('/')[0]
                if module and module not in imports:
                    imports.append(module)
        # CommonJS: require('module')
        for match in re.finditer(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content):
            module = match.group(1)
            if not module.startswith('.'):
                module = module.split('/')[0]
                if module and module not in imports:
                    imports.append(module)
        return imports[:self.MAX_IMPORTS]

    def _extract_js_exports(self, content: str) -> list:
        """Extract JavaScript/TypeScript exports."""
        exports = []
        for match in re.finditer(r'export\s+(?:default\s+)?(?:const|let|var|function|class)\s+(\w+)', content):
            exports.append(match.group(1))
        return exports[:self.MAX_EXPORTS]

    def _extract_js_functions(self, content: str) -> list:
        """Extract JavaScript function names."""
        functions = []
        patterns = [
            r'function\s+(\w+)\s*\(',                                    # function foo(
            r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>',  # const foo = () =>
            r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\w+\s*=>',   # const foo = x =>
            r'(\w+)\s*:\s*(?:async\s*)?function\s*\(',                   # foo: function(
            r'(\w+)\s*\([^)]*\)\s*\{',                                   # foo() { (method shorthand)
        ]
        # Skip JS reserved words that might false-positive match
        reserved = {'function', 'async', 'if', 'for', 'while', 'switch', 'catch'}
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                name = match.group(1)
                if name and name not in functions and name not in reserved:
                    functions.append(name)
        return functions[:self.MAX_FUNCTIONS]

    def _extract_js_classes(self, content: str) -> list:
        """Extract JavaScript class names."""
        classes = []
        for match in re.finditer(r'class\s+(\w+)', content):
            classes.append(match.group(1))
        return classes[:self.MAX_CLASSES]

    def _build_structure(self):
        """Build directory structure summary."""
        for path, info in self.files.items():
            # Track directories
            dir_path = str(Path(path).parent)
            if dir_path not in self.structure['directories']:
                self.structure['directories'][dir_path] = {
                    'files': 0,
                    'lines': 0,
                    'languages': set(),
                }
            self.structure['directories'][dir_path]['files'] += 1
            self.structure['directories'][dir_path]['lines'] += info.lines
            self.structure['directories'][dir_path]['languages'].add(info.language)

            # Track file types
            lang = info.language
            if lang not in self.structure['file_types']:
                self.structure['file_types'][lang] = {'files': 0, 'lines': 0}
            self.structure['file_types'][lang]['files'] += 1
            self.structure['file_types'][lang]['lines'] += info.lines

            # Total lines
            self.structure['total_lines'] += info.lines

        # Convert sets to lists for JSON serialization
        for dir_info in self.structure['directories'].values():
            dir_info['languages'] = list(dir_info['languages'])

    def _find_entry_points(self):
        """Find likely entry points in the codebase."""
        entry_point_patterns = [
            'main.py', 'app.py', 'index.py', 'cli.py', 'server.py',
            'main.js', 'index.js', 'app.js', 'server.js',
            'main.ts', 'index.ts', 'app.ts',
            'main.go', 'cmd/main.go',
        ]

        for path, info in self.files.items():
            filename = Path(path).name
            if filename in entry_point_patterns:
                self.entry_points.append({
                    'path': path,
                    'type': 'main',
                    'description': info.description or f"Entry point: {filename}",
                })

            # Check for __main__ in Python
            if info.language == 'python':
                if '__main__' in str(info.functions):
                    self.entry_points.append({
                        'path': path,
                        'type': 'executable',
                        'description': info.description or "Executable module",
                    })

    def _extract_key_concepts(self):
        """Extract key concepts from class and function names."""
        # Collect all significant names
        all_classes = []
        all_functions = []

        for info in self.files.values():
            all_classes.extend(info.classes)
            all_functions.extend(info.functions)

        # Find most common/important concepts
        # (In a real implementation, this would be more sophisticated)
        self.key_concepts = list(set(all_classes))[:self.MAX_KEY_CONCEPTS]

    def _load_state(self) -> Optional[dict]:
        """Load previously saved analysis state for incremental updates.

        Returns:
            Dict with cached state including file_hashes and file_data,
            or None if no valid state exists.
        """
        if not self.state_file.exists():
            return None

        try:
            state = json.loads(self.state_file.read_text())
            # Validate required fields
            if 'file_hashes' not in state:
                return None
            return state
        except (json.JSONDecodeError, OSError):
            return None

    def _restore_file_info(self, data: dict) -> FileInfo:
        """Restore a FileInfo object from cached data."""
        return FileInfo(
            path=data['path'],
            size=data['size'],
            lines=data['lines'],
            language=data['language'],
            imports=data.get('imports', []),
            exports=data.get('exports', []),
            functions=data.get('functions', []),
            classes=data.get('classes', []),
            methods=data.get('methods', {}),
            description=data.get('description', ''),
            class_docstrings=data.get('class_docstrings', {}),
            function_docstrings=data.get('function_docstrings', {}),
            signatures=data.get('signatures', {}),
        )

    def _save_state(self):
        """Save analysis state for incremental updates.

        Uses atomic write (tmp file + rename) to prevent corruption if
        the process is interrupted mid-write. Saves file data so unchanged
        files can be restored without re-parsing.
        """
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)

            # Serialize FileInfo objects to dicts
            file_data = {}
            for path, info in self.files.items():
                file_data[path] = {
                    'path': info.path,
                    'size': info.size,
                    'lines': info.lines,
                    'language': info.language,
                    'imports': info.imports,
                    'exports': info.exports,
                    'functions': info.functions,
                    'classes': info.classes,
                    'methods': info.methods,
                    'description': info.description,
                    'signatures': info.signatures,
                }

            state = {
                'analyzed_at': datetime.now(timezone.utc).isoformat(),
                'files_count': len(self.files),
                'total_lines': self.structure['total_lines'],
                'file_hashes': {
                    path: f"{info.size}:{info.lines}"
                    for path, info in self.files.items()
                },
                'file_data': file_data,
            }

            # Atomic write: write to tmp file then rename
            tmp_file = self.state_file.with_suffix('.tmp')
            tmp_file.write_text(json.dumps(state, indent=2))
            tmp_file.rename(self.state_file)
        except OSError:
            # Log warning but don't fail analysis - state is optional
            pass

    # ========================================================================
    # Documentation Generation
    # ========================================================================

    def generate(self, doc_type: str = 'architecture', output_path: Path = None) -> str:
        """
        Generate documentation of the specified type.

        Args:
            doc_type: One of 'architecture', 'onboarding', 'api', 'readme'
            output_path: Where to write the output (default: docs/<type>[-level].md)

        Returns:
            The generated documentation content
        """
        if not self.files:
            self.analyze()

        generators = {
            'architecture': self._generate_architecture,
            'onboarding': self._generate_onboarding,
            'api': self._generate_api,
            'readme': self._generate_readme,
            'insights': self._generate_insights,
        }

        if doc_type not in generators:
            raise ValueError(f"Unknown doc type: {doc_type}. Use: {list(generators.keys())}")

        content = generators[doc_type]()

        # Write to file with level-specific suffix (mid is default, no suffix)
        if output_path is None:
            suffix = f"-{self.skill_level}" if self.skill_level != 'mid' else ""
            output_path = self.output_dir / f"{doc_type}{suffix}.md"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)

        return content

    def generate_context(self) -> str:
        """Generate structured context for Claude Code to analyze.

        This method outputs a structured analysis that can be piped to Claude Code
        for semantic understanding and enhanced documentation generation. The output
        is designed to be read by an AI, not directly by humans.

        Returns:
            Structured markdown with project analysis for AI consumption.
        """
        if not self.files:
            self.analyze()

        project_type = self._detect_project_type()
        project_name = self.metadata.name or self.project_dir.resolve().name

        lines = [
            "# Project Analysis Context",
            "",
            "This is a structured analysis for AI-assisted documentation generation.",
            "",
            "---",
            "",
            "## Project Identity",
            "",
            f"- **Name:** {project_name}",
            f"- **Description:** {self.metadata.description or '(not specified)'}",
            f"- **Version:** {self.metadata.version or '(not specified)'}",
            f"- **License:** {self.metadata.license or '(not specified)'}",
            "",
            "## Detected Project Type",
            "",
            f"- **Primary Type:** {project_type.primary}",
            f"- **Secondary Types:** {', '.join(project_type.secondary_types) or '(none)'}",
            f"- **Framework:** {project_type.framework or '(none detected)'}",
            f"- **Build System:** {project_type.build_system or '(unknown)'}",
            f"- **Confidence:** {project_type.confidence:.0%}",
            f"- **Characteristics:** {', '.join(project_type.characteristics) or '(none)'}",
            "",
            "## Languages & File Types",
            "",
        ]

        # File type breakdown
        for lang, info in sorted(self.structure['file_types'].items(), key=lambda x: -x[1]['files']):
            lines.append(f"- {lang}: {info['files']} files ({info['lines']:,} lines)")
        lines.append("")

        # Key modules with their purposes
        lines.extend([
            "## Key Modules",
            "",
        ])

        for path, file_info in sorted(self.files.items()):
            if file_info.classes or len(file_info.functions) > 2:
                desc = self._get_file_description(Path(path).name, file_info, file_info.description)
                lines.append(f"### `{path}`")
                lines.append("")
                lines.append(f"**Purpose:** {desc}")
                lines.append("")

                if file_info.classes:
                    lines.append("**Classes:**")
                    for cls in file_info.classes[:5]:
                        docstring = file_info.class_docstrings.get(cls, '')
                        if docstring:
                            lines.append(f"- `{cls}` - {self._smart_truncate(docstring, 100)}")
                        else:
                            lines.append(f"- `{cls}`")
                    lines.append("")

                if file_info.functions:
                    public_funcs = [f for f in file_info.functions if not f.startswith('_')][:5]
                    if public_funcs:
                        lines.append("**Key Functions:**")
                        for func in public_funcs:
                            docstring = file_info.function_docstrings.get(func, '')
                            if docstring:
                                lines.append(f"- `{func}()` - {self._smart_truncate(docstring, 80)}")
                            else:
                                lines.append(f"- `{func}()`")
                        lines.append("")

        # Dependencies
        lines.extend([
            "## External Dependencies",
            "",
        ])
        all_imports = set()
        for file_info in self.files.values():
            all_imports.update(file_info.imports)

        # Filter to third-party only
        # Exclude: stdlib, single-char artifacts, Java/Kotlin package prefixes
        PACKAGE_PREFIXES = {'java', 'javax', 'org', 'com', 'io', 'net', 'kotlin', 'kotlinx'}
        third_party = sorted([
            i for i in all_imports
            if i
            and len(i) > 1  # Exclude single-char regex artifacts like '(' or '{'
            and i.isalnum()  # Must be alphanumeric (no special chars)
            and '.' not in i
            and i not in STDLIB_MODULES
            and i not in PACKAGE_PREFIXES
        ])
        if third_party:
            for imp in third_party[:15]:
                lines.append(f"- {imp}")
        else:
            lines.append("- (no third-party dependencies detected)")
        lines.append("")

        # Entry points
        if self.entry_points:
            lines.extend([
                "## Entry Points",
                "",
            ])
            for ep in self.entry_points[:5]:
                lines.append(f"- `{ep['path']}` - {ep['description']}")
            lines.append("")

        # Architectural patterns (heuristic detection)
        lines.extend([
            "## Detected Patterns",
            "",
        ])
        patterns = self._detect_architectural_patterns()
        if patterns:
            for pattern in patterns:
                lines.append(f"- {pattern}")
        else:
            lines.append("- (no specific patterns detected)")
        lines.append("")

        # Instructions for Claude
        lines.extend([
            "---",
            "",
            "## Analysis Request",
            "",
            "Based on this project analysis, please provide:",
            "",
            "1. **Architecture insights** - How the components interact",
            "2. **Code quality observations** - Patterns, anti-patterns, suggestions",
            "3. **Onboarding recommendations** - Key concepts a new developer should understand",
            "4. **Documentation gaps** - What's missing or unclear",
            "",
        ])

        return '\n'.join(lines)

    def _detect_architectural_patterns(self) -> list:
        """Detect common architectural patterns in the codebase."""
        patterns = []

        all_classes = set()
        all_dirs = set()

        for path, file_info in self.files.items():
            all_classes.update(file_info.classes)
            for part in Path(path).parts[:-1]:
                all_dirs.add(part.lower())

        # Pattern detection
        if any('Handler' in c or 'Controller' in c for c in all_classes):
            patterns.append("Handler/Controller pattern (request handling)")

        if any('Service' in c for c in all_classes):
            patterns.append("Service layer pattern (business logic separation)")

        if any('Repository' in c or 'DAO' in c for c in all_classes):
            patterns.append("Repository pattern (data access abstraction)")

        if any('Factory' in c for c in all_classes):
            patterns.append("Factory pattern (object creation)")

        if any('Singleton' in c for c in all_classes):
            patterns.append("Singleton pattern")

        if 'models' in all_dirs or 'entities' in all_dirs:
            patterns.append("Domain models (models/ or entities/)")

        if 'middleware' in all_dirs:
            patterns.append("Middleware pattern")

        if 'hooks' in all_dirs:
            patterns.append("Hooks pattern (lifecycle callbacks)")

        if 'plugins' in all_dirs or 'extensions' in all_dirs:
            patterns.append("Plugin architecture")

        if any('Agent' in c for c in all_classes):
            patterns.append("Agent pattern (autonomous actors)")

        if any('Command' in c for c in all_classes):
            patterns.append("Command pattern")

        if any('Observer' in c or 'Listener' in c for c in all_classes):
            patterns.append("Observer/Listener pattern")

        return patterns

    def _generate_insights(self) -> str:
        """Generate insights documentation.

        This doc type outputs the structured context and prompts Claude Code
        to provide semantic analysis. The output includes both the analysis
        context and a request for AI-powered insights.

        Note: This is meant to be run within a Claude Code session where
        the AI can read the context and provide intelligent analysis.
        """
        context = self.generate_context()

        lines = [
            "# Project Insights",
            "",
            "This document contains AI-assisted analysis of the codebase.",
            "",
            "---",
            "",
            context,
            "",
            "---",
            "",
            "## How to Use This Document",
            "",
            "This document was generated by `claudia docs generate --type insights`.",
            "",
            "When run within a Claude Code session, the AI assistant can read this",
            "structured analysis and provide:",
            "",
            "- Architectural recommendations",
            "- Code quality insights",
            "- Refactoring suggestions",
            "- Documentation improvements",
            "",
            "To get AI insights, run this command in Claude Code and ask:",
            "\"Based on this project analysis, what are the key architectural insights?\"",
            "",
        ]

        return '\n'.join(lines)

    # ------------------------------------------------------------------------
    # Section Helpers (reusable across generation methods)
    # ------------------------------------------------------------------------

    def _section_project_structure(self, as_code_block: bool = False, detailed: bool = False) -> list:
        """Generate project structure section.

        Args:
            as_code_block: If True, wrap in code block (for architecture).
                          If False, use bullet list (for onboarding).
            detailed: If True (and junior level), show individual file descriptions.

        Returns:
            List of lines for the section.
        """
        lines = []
        dir_limit = {'junior': 999, 'mid': 10, 'senior': 5}[self.skill_level]
        dirs_to_show = sorted(self.structure['directories'].items())[:dir_limit]

        if as_code_block:
            lines.append("```")
            for dir_path, info in dirs_to_show:
                if dir_path == '.':
                    continue
                indent = "  " * dir_path.count('/')
                langs = ', '.join(info['languages'])
                lines.append(f"{indent}{dir_path}/ ({info['files']} files, {langs})")
            lines.append("```")
        elif detailed and self._is_level('junior'):
            # Detailed view: show each file with its description
            for dir_path, info in dirs_to_show:
                if dir_path == '.':
                    continue

                # Get files in this directory
                dir_files = [(p, f) for p, f in self.files.items()
                             if str(Path(p).parent) == dir_path]

                if dir_files:
                    lines.append(f"**{dir_path}/**")
                    lines.append("")
                    for file_path, file_info in sorted(dir_files):
                        filename = Path(file_path).name
                        desc = file_info.description or ''
                        # Get description: prefer docstring, fall back to inference
                        description = self._get_file_description(filename, file_info, desc)
                        lines.append(f"- `{filename}` - {description}")
                    lines.append("")
        else:
            for dir_path, info in dirs_to_show:
                if dir_path == '.':
                    lines.append("- **Root**: Configuration files, entry points")
                else:
                    if self._is_level('junior'):
                        langs = ', '.join(info['languages'])
                        lines.append(f"- **{dir_path}/**: {info['files']} {langs} files")
                    else:
                        lines.append(f"- **{dir_path}/**: {info['files']} files")

        return lines

    def _get_file_description(self, filename: str, file_info, docstring: str) -> str:
        """Get a file description from docstring or inference.

        Tries docstring first, then falls back to pattern-based inference.

        Args:
            filename: The file name (e.g., 'cli.py')
            file_info: FileInfo object with classes/functions
            docstring: Module docstring (may be empty)

        Returns:
            A brief description (max ~70 chars).
        """
        # Try docstring first
        if docstring:
            # Remove newlines and extra whitespace
            desc = ' '.join(docstring.split())
            # Find first sentence
            period_idx = desc.find('.')
            if period_idx > 0 and period_idx < 70:
                return desc[:period_idx + 1]
            elif len(desc) <= 70:
                return desc
            else:
                # Truncate at word boundary
                truncated = desc[:67]
                last_space = truncated.rfind(' ')
                if last_space > 40:
                    return truncated[:last_space] + '...'
                return truncated + '...'

        # Fall back to inference
        return self._infer_file_purpose(filename, file_info)

    def _infer_file_purpose(self, filename: str, file_info) -> str:
        """Infer a file's purpose from its name and contents.

        Uses generic filename patterns that apply to most projects.

        Args:
            filename: The file name (e.g., 'cli.py')
            file_info: FileInfo object with classes/functions

        Returns:
            A brief description of the file's purpose.
        """
        # Common filename patterns (generic, not project-specific)
        name_lower = filename.lower().replace('.py', '').replace('.js', '').replace('.ts', '')

        patterns = {
            # Entry points
            'cli': 'Command-line interface',
            'main': 'Application entry point',
            'app': 'Application entry point',
            'index': 'Module entry point',
            '__main__': 'Package entry point',
            # Common module types
            'utils': 'Utility functions',
            'helpers': 'Helper functions',
            'config': 'Configuration handling',
            'settings': 'Settings and configuration',
            'constants': 'Constants and defaults',
            'models': 'Data models and schemas',
            'schemas': 'Data schemas and validation',
            'types': 'Type definitions',
            # API/Server
            'api': 'API implementation',
            'routes': 'Route handlers',
            'views': 'View handlers',
            'handlers': 'Request handlers',
            'server': 'Server implementation',
            'client': 'Client implementation',
            # Data
            'db': 'Database operations',
            'database': 'Database operations',
            'storage': 'Data storage',
            'cache': 'Caching layer',
            # Auth
            'auth': 'Authentication',
            'permissions': 'Authorization and permissions',
            # Testing
            'test_': 'Test suite',
            'conftest': 'Test configuration and fixtures',
            # Misc
            'errors': 'Error definitions',
            'exceptions': 'Exception classes',
            'logging': 'Logging configuration',
            'middleware': 'Middleware components',
        }

        for pattern, desc in patterns.items():
            if pattern in name_lower:
                return desc

        # Fall back to inferring from classes - try to describe what they do
        if file_info.classes:
            main_class = file_info.classes[0]
            # Try to infer purpose from class name
            class_lower = main_class.lower()
            if 'handler' in class_lower:
                return f'{main_class} - request/event handler'
            elif 'manager' in class_lower:
                return f'{main_class} - resource management'
            elif 'client' in class_lower:
                return f'{main_class} - API client'
            elif 'server' in class_lower:
                return f'{main_class} - server implementation'
            elif 'controller' in class_lower:
                return f'{main_class} - controller logic'
            elif 'service' in class_lower:
                return f'{main_class} - service layer'
            elif 'model' in class_lower:
                return f'{main_class} - data model'
            elif 'view' in class_lower:
                return f'{main_class} - view layer'
            elif 'test' in class_lower:
                return f'Tests for {main_class.replace("Test", "")}'
            else:
                return f'Implements {main_class}'

        # Fall back to inferring from function names
        if file_info.functions:
            funcs = file_info.functions[:5]  # Look at first 5 functions
            # Try to find a common theme
            func_str = ' '.join(funcs).lower()
            if 'render' in func_str or 'draw' in func_str or 'display' in func_str:
                return 'UI/display functions'
            elif 'parse' in func_str or 'load' in func_str or 'read' in func_str:
                return 'Data parsing and loading'
            elif 'save' in func_str or 'write' in func_str or 'export' in func_str:
                return 'Data output and persistence'
            elif 'validate' in func_str or 'check' in func_str:
                return 'Validation functions'
            elif 'format' in func_str:
                return 'Formatting utilities'
            elif 'handle' in func_str or 'process' in func_str:
                return 'Event/request processing'
            elif 'cmd_' in func_str or 'command' in func_str:
                return 'Command implementations'
            elif len(file_info.functions) == 1:
                return f'Implements {file_info.functions[0]}()'
            else:
                return f'{len(file_info.functions)} utility functions'

        return 'Module implementation'

    def _section_dependencies(self) -> list:
        """Generate external dependencies section.

        Returns:
            List of lines listing external (non-stdlib, non-internal) imports.
        """
        lines = []
        all_imports = set()
        for info in self.files.values():
            all_imports.update(info.imports)

        # Filter to external dependencies
        internal_modules = {Path(p).stem for p in self.files.keys()}
        internal_packages = set()
        for p in self.files.keys():
            parts = Path(p).parts
            for part in parts:
                clean_part = part.replace('.py', '')
                if clean_part:
                    internal_packages.add(clean_part)

        if self.metadata.name:
            internal_packages.add(self.metadata.name)

        external = sorted(all_imports - internal_modules - internal_packages)[:self.MAX_DEPENDENCIES]

        if external:
            if self._is_level('junior'):
                lines.append("External packages this project uses:")
                lines.append("")
            for imp in external:
                lines.append(f"- `{imp}`")
        else:
            lines.append("Standard library only (no external dependencies).")

        return lines

    def _onboarding_prerequisites(self, languages: set) -> list:
        """Generate prerequisites section for onboarding.

        Args:
            languages: Set of detected languages (e.g., {'python', 'javascript'})

        Returns:
            List of lines for prerequisites.
        """
        lines = []
        python_version = self.metadata.python_requires or "3.10+"
        python_version = python_version.replace('>=', '').strip()
        if not python_version.endswith('+'):
            python_version += '+'

        if 'python' in languages:
            if self._is_level('junior'):
                lines.extend([
                    f"- **Python {python_version}** - [Download Python](https://python.org/downloads/)",
                    "  - Verify with: `python --version` or `python3 --version`",
                    "- **pip** - Usually comes with Python. Verify with: `pip --version`",
                    "- **Git** - [Download Git](https://git-scm.com/downloads)",
                ])
            else:
                lines.extend([
                    f"- Python {python_version}",
                    "- pip or pipenv",
                ])

        if 'javascript' in languages or 'typescript' in languages:
            if self._is_level('junior'):
                lines.extend([
                    "- **Node.js 18+** - [Download Node.js](https://nodejs.org/)",
                    "  - Verify with: `node --version`",
                    "- **npm** - Comes with Node.js. Verify with: `npm --version`",
                ])
            else:
                lines.extend([
                    "- Node.js 18+",
                    "- npm or yarn",
                ])

        return lines

    def _onboarding_setup(self, languages: set, repo_url: str, project_name: str) -> list:
        """Generate setup instructions for onboarding.

        Args:
            languages: Set of detected languages
            repo_url: Repository URL
            project_name: Project name

        Returns:
            List of lines for setup section.
        """
        lines = []

        if 'python' in languages:
            lines.extend([
                "### Setup",
                "",
                "```bash",
                "# Clone the repository",
                f"git clone {repo_url}",
                f"cd {project_name}",
                "",
                "# Create virtual environment",
                "python -m venv venv",
                "source venv/bin/activate  # or venv\\Scripts\\activate on Windows",
                "",
                "# Install dependencies",
                "pip install -e .",
                "```",
                "",
            ])

            if self._is_level('junior'):
                lines.extend([
                    "#### Troubleshooting Setup",
                    "",
                    "**\"python\" command not found?**",
                    "- Try `python3` instead of `python`",
                    "- Make sure Python is in your PATH",
                    "",
                    "**Permission denied on `source venv/bin/activate`?**",
                    "- Make sure you're in the project directory",
                    "- On Windows, use: `venv\\Scripts\\activate`",
                    "",
                    "**pip install fails?**",
                    "- Make sure your virtual environment is activated (you should see `(venv)` in your prompt)",
                    "- Try: `pip install --upgrade pip` first",
                    "",
                ])

        if 'javascript' in languages or 'typescript' in languages:
            lines.extend([
                "### Setup",
                "",
                "```bash",
                "# Clone and install",
                f"git clone {repo_url}",
                f"cd {project_name}",
                "npm install",
                "```",
                "",
            ])

        return lines

    def _onboarding_workflow(self) -> list:
        """Generate development workflow section for onboarding.

        Returns:
            List of lines for workflow section.
        """
        lines = ["## Development Workflow", ""]

        if self._is_level('junior'):
            lines.extend([
                "Follow these steps when making changes:",
                "",
                "### 1. Create a feature branch",
                "",
                "```bash",
                "# Start from the main branch",
                "git checkout main",
                "git pull origin main",
                "",
                "# Create your feature branch",
                "git checkout -b feature/my-feature",
                "```",
                "",
                "### 2. Make your changes",
                "",
                "- Edit the files you need to change",
                "- Test your changes locally",
                "- Commit frequently with clear messages",
                "",
                "```bash",
                "git add .",
                "git commit -m \"Add: brief description of change\"",
                "```",
                "",
                "### 3. Run tests",
                "",
                "Before submitting, make sure all tests pass.",
                "",
                "### 4. Submit a pull request",
                "",
                "```bash",
                "git push origin feature/my-feature",
                "```",
                "",
                "Then open a Pull Request on GitHub.",
                "",
            ])
        else:
            lines.extend([
                "1. Create a feature branch: `git checkout -b feature/my-feature`",
                "2. Make your changes",
                "3. Run tests (if available)",
                "4. Submit a pull request",
                "",
            ])

        return lines

    def _onboarding_pitfalls(self) -> list:
        """Generate common pitfalls section (junior only).

        Returns:
            List of lines for pitfalls section, or empty list if not junior.
        """
        if not self._is_level('junior'):
            return []

        return [
            "## Common Pitfalls",
            "",
            "Avoid these common mistakes:",
            "",
            "### 1. Forgetting to activate the virtual environment",
            "",
            "**Symptom:** `ModuleNotFoundError` when running code",
            "",
            "**Solution:** Run `source venv/bin/activate` (or `venv\\Scripts\\activate` on Windows)",
            "",
            "### 2. Committing to main branch directly",
            "",
            "**Symptom:** Push rejected or PR conflicts",
            "",
            "**Solution:** Always create a feature branch first",
            "",
            "### 3. Not pulling latest changes",
            "",
            "**Symptom:** Merge conflicts when submitting PR",
            "",
            "**Solution:** Run `git pull origin main` before starting work",
            "",
        ]

    def _is_test_file(self, path: str) -> bool:
        """Check if a file is a test file that should be excluded from framework detection.

        This method focuses on the FILENAME, not the directory path.
        Files in tests/ directories that are fixtures/examples should NOT be skipped.

        Skipped patterns:
        - conftest.py (pytest configuration)
        - test_*.py, *_test.py (Python tests)
        - *.test.js, *.spec.ts, etc. (JS/TS tests)
        - *_test.go (Go tests)
        - *_test.rs (Rust tests)
        - *Test.java, *Spec.java (Java tests)

        NOT skipped:
        - fixture_app.py (example app for testing framework detection)
        - Any file that doesn't match test patterns
        """
        filename = Path(path).name

        # Pytest configuration files
        if filename == 'conftest.py':
            return True

        # Python test files
        if filename.startswith('test_') and filename.endswith('.py'):
            return True
        if filename.endswith('_test.py'):
            return True

        # JavaScript/TypeScript test files
        if any(filename.endswith(ext) for ext in ['.test.js', '.test.ts', '.test.jsx', '.test.tsx',
                                                    '.spec.js', '.spec.ts', '.spec.jsx', '.spec.tsx']):
            return True

        # Go test files
        if filename.endswith('_test.go'):
            return True

        # Rust test files (in tests/ directory are often integration tests)
        if filename.endswith('_test.rs'):
            return True

        # Java/Kotlin test files
        if filename.endswith('Test.java') or filename.endswith('Spec.java'):
            return True
        if filename.endswith('Test.kt') or filename.endswith('Spec.kt'):
            return True

        return False

    def _detect_project_type(self) -> ProjectType:
        """Detect the type of project based on file patterns and structure.

        Analyzes the codebase to determine if this is a:
        - cli: Command-line tool (cli.py, __main__.py, argparse usage)
        - library: Reusable library/package (pkg/, lib.rs, no entry points)
        - api: REST/HTTP API (routes/, handlers/, FastAPI/Flask patterns)
        - webapp: Web application (templates/, static/, frontend frameworks)
        - microservice: Small containerized service (Dockerfile + small scope)

        Returns:
            ProjectType with primary type, framework, build system, and confidence.
        """
        scores = {
            'cli': 0.0,
            'library': 0.0,
            'api': 0.0,
            'webapp': 0.0,
            'microservice': 0.0,
        }
        characteristics = []
        framework_scores = {}  # Track scores per framework for deterministic selection
        build_system = ''

        # Gather file names and directory names for pattern matching
        # We need to scan the filesystem, not just self.files (which only has analyzed source files)
        all_files = set()
        all_dirs = set()

        # First, add analyzed source files
        for path in self.files:
            parts = Path(path).parts
            all_files.add(parts[-1])  # filename
            for part in parts[:-1]:
                all_dirs.add(part)

        # Also scan the filesystem for config files and directories
        # This catches Dockerfile, pyproject.toml, package.json, templates/, etc.
        try:
            for item in self.project_dir.rglob('*'):
                if item.is_file():
                    all_files.add(item.name)
                    # Collect directory names from the path
                    rel_path = item.relative_to(self.project_dir)
                    for part in rel_path.parts[:-1]:
                        all_dirs.add(part)
                elif item.is_dir():
                    all_dirs.add(item.name)
        except (OSError, PermissionError):
            pass  # Graceful degradation if filesystem access fails

        # Build system detection
        if 'pyproject.toml' in all_files or 'setup.py' in all_files:
            build_system = 'pip'
        elif 'package.json' in all_files:
            build_system = 'npm'
        elif 'Cargo.toml' in all_files:
            build_system = 'cargo'
        elif 'go.mod' in all_files:
            build_system = 'go'
        elif 'pom.xml' in all_files:
            build_system = 'maven'
        elif 'build.gradle' in all_files or 'build.gradle.kts' in all_files:
            build_system = 'gradle'
        elif 'Gemfile' in all_files:
            build_system = 'bundler'

        # --- CLI Detection ---
        cli_indicators = ['cli.py', '__main__.py', 'main.py', 'cmd.py']
        for indicator in cli_indicators:
            if indicator in all_files:
                scores['cli'] += 0.3
                characteristics.append(f'has {indicator}')

        if 'cmd' in all_dirs or 'commands' in all_dirs:
            scores['cli'] += 0.2
            characteristics.append('cmd/ directory')

        # Check for argparse/click/typer imports
        for path, file_info in self.files.items():
            if 'cli' in path.lower() or '__main__' in path:
                imports = file_info.imports
                if any(imp in imports for imp in ['argparse', 'click', 'typer']):
                    scores['cli'] += 0.3
                    characteristics.append('CLI framework detected')
                    break

        # --- API Detection ---
        api_dirs = ['routes', 'handlers', 'endpoints', 'api', 'controllers']
        for d in api_dirs:
            if d in all_dirs:
                scores['api'] += 0.25
                characteristics.append(f'{d}/ directory')

        api_files = ['server.py', 'app.py', 'main.go', 'server.go', 'routes.py']
        for f in api_files:
            if f in all_files:
                scores['api'] += 0.15

        # Framework detection from imports
        # Skip test files - they often contain example/mock code that shouldn't affect detection
        for path, file_info in self.files.items():
            if self._is_test_file(path):
                continue
            imports = file_info.imports
            # Python API frameworks - track scores for deterministic selection
            if 'fastapi' in imports:
                scores['api'] += 0.4
                framework_scores['FastAPI'] = framework_scores.get('FastAPI', 0) + 0.4
            if 'flask' in imports:
                scores['api'] += 0.35
                framework_scores['Flask'] = framework_scores.get('Flask', 0) + 0.35
            if 'django' in imports:
                scores['api'] += 0.35
                framework_scores['Django'] = framework_scores.get('Django', 0) + 0.35
            if 'express' in imports:
                scores['api'] += 0.4
                framework_scores['Express'] = framework_scores.get('Express', 0) + 0.4
            # Go frameworks
            if 'gin-gonic' in str(imports) or 'github.com/gin-gonic' in str(imports):
                scores['api'] += 0.4
                framework_scores['Gin'] = framework_scores.get('Gin', 0) + 0.4
            if 'echo' in str(imports) or 'labstack/echo' in str(imports):
                scores['api'] += 0.4
                framework_scores['Echo'] = framework_scores.get('Echo', 0) + 0.4
            # Rust frameworks
            if 'actix' in str(imports):
                scores['api'] += 0.4
                framework_scores['Actix'] = framework_scores.get('Actix', 0) + 0.4
            if 'rocket' in str(imports):
                scores['api'] += 0.4
                framework_scores['Rocket'] = framework_scores.get('Rocket', 0) + 0.4

        # --- Webapp Detection ---
        webapp_dirs = ['templates', 'static', 'public', 'assets', 'views']
        for d in webapp_dirs:
            if d in all_dirs:
                scores['webapp'] += 0.2
                characteristics.append(f'{d}/ directory')

        # Frontend frameworks
        if 'components' in all_dirs:
            scores['webapp'] += 0.15
        if any(f.endswith('.html') or f.endswith('.jsx') or f.endswith('.tsx') for f in all_files):
            scores['webapp'] += 0.2

        for path, file_info in self.files.items():
            if self._is_test_file(path):
                continue
            imports = file_info.imports
            if 'react' in imports or 'React' in str(file_info.exports):
                scores['webapp'] += 0.3
                framework_scores['React'] = framework_scores.get('React', 0) + 0.3
            if 'vue' in imports:
                scores['webapp'] += 0.3
                framework_scores['Vue'] = framework_scores.get('Vue', 0) + 0.3
            if 'angular' in str(imports):
                scores['webapp'] += 0.3
                framework_scores['Angular'] = framework_scores.get('Angular', 0) + 0.3
            if 'svelte' in imports:
                scores['webapp'] += 0.3
                framework_scores['Svelte'] = framework_scores.get('Svelte', 0) + 0.3

        # --- Library Detection ---
        lib_dirs = ['pkg', 'lib', 'internal', 'src/lib']
        for d in lib_dirs:
            if d in all_dirs:
                scores['library'] += 0.2

        # Rust library indicator
        if 'lib.rs' in all_files:
            scores['library'] += 0.4
            characteristics.append('lib.rs (Rust library)')

        # No entry points suggests library
        has_entry = any(f in all_files for f in ['main.py', 'cli.py', '__main__.py', 'main.go', 'main.rs'])
        if not has_entry:
            scores['library'] += 0.3
            characteristics.append('no main entry point')

        # Published packages are usually libraries
        if self.metadata.keywords:
            scores['library'] += 0.1

        # --- Microservice Detection ---
        if 'Dockerfile' in all_files or 'dockerfile' in all_files:
            scores['microservice'] += 0.3
            characteristics.append('Dockerfile present')

        if 'docker-compose.yml' in all_files or 'docker-compose.yaml' in all_files:
            scores['microservice'] += 0.15

        # Small scope = microservice
        total_files = len(self.files)
        if total_files < 15:
            scores['microservice'] += 0.2
            characteristics.append('small codebase')
        elif total_files < 30:
            scores['microservice'] += 0.1

        # Kubernetes/deployment indicators
        k8s_files = ['k8s.yaml', 'deployment.yaml', 'service.yaml', 'helm']
        for f in k8s_files:
            if f in all_files or f in all_dirs:
                scores['microservice'] += 0.15
                characteristics.append('k8s deployment')
                break

        # --- Determine Primary Type ---
        # Normalize scores and pick highest
        max_score = max(scores.values())
        if max_score == 0:
            # Default to library if nothing detected
            primary = 'library'
            confidence = 0.2
        else:
            primary = max(scores, key=scores.get)
            confidence = min(max_score, 1.0)

        # CLI can also be an API (e.g., Flask-CLI)
        # Prefer more specific type when scores are close
        if primary == 'library' and scores['api'] > 0.3:
            primary = 'api'
            confidence = scores['api']
        elif primary == 'library' and scores['cli'] > 0.3:
            primary = 'cli'
            confidence = scores['cli']

        # Detect secondary types (hybrid projects like Flask+Click = API+CLI)
        # Types with score > 0.25 that aren't the primary type
        SECONDARY_THRESHOLD = 0.25
        secondary_types = [
            t for t, score in sorted(scores.items(), key=lambda x: -x[1])
            if t != primary and score >= SECONDARY_THRESHOLD
        ]

        # Select highest-scoring framework (deterministic)
        framework = ''
        if framework_scores:
            framework = max(framework_scores, key=framework_scores.get)

        return ProjectType(
            primary=primary,
            framework=framework,
            build_system=build_system,
            confidence=round(confidence, 2),
            characteristics=list(set(characteristics))[:5],  # Top 5 unique
            secondary_types=secondary_types,
        )

    def _detect_cli_info(self) -> dict:
        """Detect if this is a CLI tool and extract command information.

        Looks for:
        - cli.py or __main__.py files
        - argparse subparser definitions
        - Entry point scripts in pyproject.toml

        Returns:
            dict with 'is_cli', 'cli_name', 'commands', 'has_subcommands'
        """
        info = {
            'is_cli': False,
            'cli_name': self.metadata.name or '',
            'commands': [],
            'has_subcommands': False,
            'description': self.metadata.description or '',
        }

        # Find CLI entry point - check filename at end of path
        cli_filenames = ['cli.py', '__main__.py', 'main.py']
        cli_file_info = None
        cli_path = None

        for path, file_info in self.files.items():
            # Get just the filename from the full path
            filename = Path(path).name
            if filename in cli_filenames:
                cli_file_info = file_info
                cli_path = path
                info['is_cli'] = True
                # Prefer cli.py over others if we find it
                if filename == 'cli.py':
                    break

        if not cli_file_info:
            return info

        # Try to read the CLI file and extract subcommands
        try:
            cli_full_path = self.project_dir / cli_path
            content = cli_full_path.read_text(errors='ignore')

            # Strategy: Find the main subparsers variable name, then only extract
            # commands added to that variable (not nested subparsers)
            #
            # Pattern: subparsers = parser.add_subparsers(...)
            main_subparser_match = re.search(
                r'(\w+)\s*=\s*\w+\.add_subparsers\s*\([^)]*dest\s*=\s*[\'"]command[\'"]',
                content
            )

            if main_subparser_match:
                main_var = main_subparser_match.group(1)  # e.g., "subparsers"

                # Only match: subparsers.add_parser('cmd', help='...')
                # This excludes nested like: archive_sub.add_parser(...)
                # Use [\w-]+ to match hyphenated commands like 'start-parallel'
                top_level_pattern = rf'{main_var}\.add_parser\s*\(\s*[\'"]([\w-]+)[\'"]'
                matches = re.findall(top_level_pattern, content)

                if matches:
                    info['has_subcommands'] = True
                    info['commands'] = list(dict.fromkeys(matches))

                # Extract help text only for top-level commands
                help_pattern = rf'{main_var}\.add_parser\s*\(\s*[\'"]([\w-]+)[\'"][^)]*help\s*=\s*[\'"]([^\'"]+)[\'"]'
                help_matches = re.findall(help_pattern, content)
                if help_matches:
                    info['command_help'] = {cmd: help_text for cmd, help_text in help_matches}
            else:
                # Fallback: generic add_parser detection (for simpler CLIs)
                subparser_pattern = r"add_parser\s*\(\s*['\"]([\w-]+)['\"]"
                matches = re.findall(subparser_pattern, content)
                if matches:
                    info['has_subcommands'] = True
                    info['commands'] = list(dict.fromkeys(matches))

            # Also look for click commands
            # Pattern: @cli.command() or @app.command()
            click_pattern = r"@\w+\.command\s*\([^)]*name\s*=\s*['\"](\w+)['\"]"
            click_matches = re.findall(click_pattern, content)
            if click_matches:
                info['has_subcommands'] = True
                info['commands'].extend(click_matches)
                info['commands'] = list(dict.fromkeys(info['commands']))

        except Exception:
            pass

        return info

    def _onboarding_usage(self, cli_info: dict, project_name: str) -> list:
        """Generate usage section for CLI tools.

        Uses dynamic pattern detection to work with any CLI, not just Claudia.
        Detects common patterns like CRUD operations, lifecycle commands,
        and prefix-based groupings.

        Args:
            cli_info: Dict from _detect_cli_info()
            project_name: Name of the project/CLI

        Returns:
            List of lines for usage section.
        """
        if not cli_info['is_cli']:
            return []

        lines = [
            "## Using " + project_name.title(),
            "",
        ]

        cli_name = cli_info['cli_name'] or project_name
        cmds = set(cli_info['commands'])
        command_help = cli_info.get('command_help', {})

        if self._is_level('junior'):
            lines.extend([
                f"After installation, the `{cli_name}` command is available in your terminal.",
                "",
                "### Getting Help",
                "",
                "```bash",
                "# Show all available commands",
                f"{cli_name} --help",
                "",
                "# Get help for a specific command",
                f"{cli_name} <command> --help",
                "```",
                "",
            ])

        # Dynamically categorize commands
        if cli_info['commands']:
            categories = self._categorize_commands(cli_info['commands'], command_help)

            if self._is_level('junior') and categories:
                lines.extend([
                    "### Command Reference",
                    "",
                ])

                for category, cat_cmds in categories.items():
                    if cat_cmds:
                        lines.append(f"**{category}:**")
                        for cmd in cat_cmds:
                            help_text = command_help.get(cmd, '')
                            if help_text:
                                lines.append(f"- `{cmd}` - {help_text}")
                            else:
                                lines.append(f"- `{cmd}`")
                        lines.append("")
            else:
                lines.extend([
                    "### Commands",
                    "",
                ])
                for cmd in cli_info['commands']:
                    help_text = command_help.get(cmd, '')
                    if help_text:
                        lines.append(f"- **{cmd}** - {help_text}")
                    else:
                        lines.append(f"- **{cmd}**")
                lines.append("")

        # Add workflow examples for junior level
        if self._is_level('junior') and cli_info['commands']:
            workflows = self._detect_workflows(cmds, cli_name, command_help)
            if workflows:
                lines.extend([
                    "### Common Workflows",
                    "",
                ])
                lines.extend(workflows)

        return lines

    def _categorize_commands(self, commands: list, command_help: dict) -> dict:
        """Dynamically categorize CLI commands based on patterns.

        Detects patterns like:
        - CRUD operations (create, list, show, update, delete)
        - Lifecycle commands (start/stop, init/cleanup)
        - Prefix-based groups (user-*, db-*, etc.)

        Args:
            commands: List of command names
            command_help: Dict mapping command names to help text

        Returns:
            Dict of {category_name: [commands]}
        """
        categories = {}
        categorized = set()

        # Pattern-based categories (generic patterns that apply to many CLIs)
        # Keywords are checked as: cmd starts with keyword, or cmd equals keyword
        patterns = {
            'Data Operations': {
                'keywords': ['create', 'add', 'new', 'list', 'show', 'get', 'view',
                             'update', 'edit', 'modify', 'delete', 'remove', 'rm',
                             'tasks', 'items', 'find', 'search', 'complete', 'reopen'],
                'commands': [],
            },
            'Lifecycle': {
                'keywords': ['start', 'stop', 'run', 'serve', 'init', 'setup',
                             'cleanup', 'destroy', 'reset', 'install', 'uninstall',
                             'up', 'down', 'restart', 'reload'],
                'commands': [],
            },
            'Configuration': {
                'keywords': ['config', 'configure', 'set', 'unset', 'env', 'settings'],
                'commands': [],
            },
            'Information': {
                'keywords': ['status', 'info', 'version', 'help', 'check', 'validate',
                             'inspect', 'describe', 'logs', 'history'],
                'commands': [],
            },
        }

        def matches_keyword(cmd: str, keyword: str) -> bool:
            """Check if command matches keyword (starts with, equals, or contains)."""
            cmd_lower = cmd.lower()
            # Normalize: remove hyphens for comparison
            cmd_normalized = cmd_lower.replace('-', '')
            # Check: exact match, starts with, or first part before hyphen
            if cmd_lower == keyword:
                return True
            if cmd_normalized.startswith(keyword):
                return True
            if '-' in cmd_lower and cmd_lower.split('-')[0] == keyword:
                return True
            return False

        # First pass: match commands to pattern categories
        for cmd in commands:
            matched = False
            for cat_name, cat_info in patterns.items():
                for keyword in cat_info['keywords']:
                    if matches_keyword(cmd, keyword):
                        cat_info['commands'].append(cmd)
                        categorized.add(cmd)
                        matched = True
                        break
                if matched:
                    break

        # Second pass: detect prefix-based groups for uncategorized commands
        prefix_groups = {}
        for cmd in commands:
            if cmd in categorized:
                continue
            if '-' in cmd:
                prefix = cmd.split('-')[0]
                if prefix not in prefix_groups:
                    prefix_groups[prefix] = []
                prefix_groups[prefix].append(cmd)
                categorized.add(cmd)

        # Build final categories (only include non-empty ones)
        for cat_name, cat_info in patterns.items():
            if cat_info['commands']:
                categories[cat_name] = cat_info['commands']

        # Add prefix groups that have multiple commands
        for prefix, cmds in prefix_groups.items():
            if len(cmds) >= 2:
                cat_name = prefix.title() + ' Commands'
                categories[cat_name] = cmds

        # Remaining uncategorized commands
        uncategorized = [c for c in commands if c not in categorized]
        if uncategorized:
            # Only fall back to flat list if VERY few commands matched
            if len(categorized) < 3:
                return {'Commands': commands}
            categories['Other'] = uncategorized

        return categories

    def _detect_workflows(self, cmds: set, cli_name: str, command_help: dict) -> list:
        """Detect and generate workflow examples based on command patterns.

        Uses generic patterns that work for any CLI, not project-specific ones.
        Handles compound commands like 'start-parallel' by checking prefixes.

        Args:
            cmds: Set of available command names
            cli_name: Name of the CLI tool
            command_help: Dict mapping command names to help text

        Returns:
            List of markdown lines for workflow sections.
        """
        lines = []

        def find_cmd(patterns: set) -> str | None:
            """Find a command matching any pattern (exact or prefix match)."""
            # First try exact matches
            exact = cmds & patterns
            if exact:
                return list(exact)[0]
            # Then try prefix matches (e.g., 'start-parallel' matches 'start')
            for cmd in cmds:
                prefix = cmd.split('-')[0] if '-' in cmd else cmd
                if prefix in patterns:
                    return cmd
            return None

        # CRUD workflow - very common pattern
        create_cmd = find_cmd({'create', 'add', 'new'})
        list_cmd = find_cmd({'list', 'ls', 'tasks', 'items'})  # 'tasks' for task-based CLIs
        show_cmd = find_cmd({'show', 'get', 'view', 'describe'})
        delete_cmd = find_cmd({'delete', 'remove', 'rm'})

        if create_cmd and (list_cmd or show_cmd):
            display_cmd = list_cmd or show_cmd
            lines.extend([
                "#### Basic Operations",
                "",
                "```bash",
                "# List/view items",
                f"{cli_name} {display_cmd}",
                "",
                "# Create a new item",
                f'{cli_name} {create_cmd} "item name"',
            ])
            if delete_cmd:
                lines.extend([
                    "",
                    "# Delete an item",
                    f"{cli_name} {delete_cmd} <item-id>",
                ])
            lines.extend(["```", ""])

        # Lifecycle workflow - start/stop patterns (handles start-parallel, etc.)
        start_cmd = find_cmd({'start', 'run', 'serve', 'up'})
        stop_cmd = find_cmd({'stop', 'halt', 'down', 'kill'})

        if start_cmd and stop_cmd:
            lines.extend([
                "#### Running the Service",
                "",
                "```bash",
                "# Start the service",
                f"{cli_name} {start_cmd}",
                "",
                "# Stop the service",
                f"{cli_name} {stop_cmd}",
                "```",
                "",
            ])

        # Init workflow
        if 'init' in cmds:
            lines.extend([
                "#### Project Setup",
                "",
                "```bash",
                "# Initialize in your project",
                "cd /path/to/your/project",
                f"{cli_name} init",
            ])
            if 'status' in cmds:
                lines.extend([
                    "",
                    "# Verify setup",
                    f"{cli_name} status",
                ])
            lines.extend(["```", ""])

        # Config workflow
        config_cmd = find_cmd({'config', 'configure', 'set'})
        if config_cmd:
            lines.extend([
                "#### Configuration",
                "",
                "```bash",
                "# View or set configuration",
                f"{cli_name} {config_cmd}",
                "```",
                "",
            ])

        # If no workflows detected, provide generic getting started
        if not lines:
            # Find the most likely "main" command
            main_cmd = find_cmd({'run', 'start', 'list', 'status', 'help'})
            if main_cmd:
                lines.extend([
                    "#### Getting Started",
                    "",
                    "```bash",
                    f"# Try the {main_cmd} command",
                    f"{cli_name} {main_cmd}",
                    "```",
                    "",
                ])

        return lines

    def _onboarding_quick_examples(self, project_type: ProjectType, project_name: str, languages: set) -> list:
        """Generate quick examples based on project type.

        Provides type-specific getting started examples:
        - api: How to start the server, make a test request
        - webapp: How to start development server, view in browser
        - library: How to import and use basic functionality
        - microservice: How to run with Docker

        Args:
            project_type: Detected project type
            project_name: Name of the project
            languages: Set of detected programming languages

        Returns:
            List of markdown lines.
        """
        lines = [
            "## Quick Examples",
            "",
            "Here are some common tasks to try after setup:",
            "",
        ]

        pkg_name = project_name.replace('-', '_').replace(' ', '_')

        if project_type.primary == 'api':
            lines.extend(self._quick_examples_api(project_type, pkg_name, languages))
        elif project_type.primary == 'webapp':
            lines.extend(self._quick_examples_webapp(project_type, pkg_name, languages))
        elif project_type.primary == 'library':
            lines.extend(self._quick_examples_library(project_type, pkg_name, languages))
        elif project_type.primary == 'microservice':
            lines.extend(self._quick_examples_microservice(project_type, pkg_name, languages))
        else:
            # Generic examples for unknown project types
            lines.extend(self._quick_examples_generic(pkg_name, languages))

        return lines

    def _quick_examples_api(self, project_type: ProjectType, pkg_name: str, languages: set) -> list:
        """Quick examples for API projects."""
        lines = [
            "### Start the development server",
            "",
            "```bash",
        ]

        framework = project_type.framework.lower()
        if framework == 'fastapi':
            lines.extend([
                "# Start with hot reload",
                "uvicorn main:app --reload",
                "",
                "# Or if using the package structure",
                f"uvicorn {pkg_name}.main:app --reload",
            ])
        elif framework == 'flask':
            lines.extend([
                "# Set development mode for auto-reload",
                "export FLASK_DEBUG=1",
                "flask run",
            ])
        elif framework == 'django':
            lines.extend([
                "python manage.py runserver",
            ])
        elif framework == 'express':
            lines.extend([
                "npm run dev  # or npm start",
            ])
        elif 'go' in languages:
            lines.extend([
                "go run main.go  # or go run .",
            ])
        else:
            lines.append("# Check package.json or README for start command")

        lines.extend([
            "```",
            "",
            "### Test the API",
            "",
            "```bash",
            "# Check if the server is running",
            "curl http://localhost:8000/  # or port 3000, 5000",
            "",
            "# View API documentation (if available)",
            "# FastAPI: http://localhost:8000/docs",
            "# Swagger: http://localhost:8000/swagger",
            "```",
            "",
        ])

        return lines

    def _quick_examples_webapp(self, project_type: ProjectType, pkg_name: str, languages: set) -> list:
        """Quick examples for web application projects."""
        lines = [
            "### Start development server",
            "",
            "```bash",
        ]

        framework = project_type.framework.lower()
        if framework == 'react':
            lines.extend([
                "npm start  # or npm run dev",
                "",
                "# Opens automatically at http://localhost:3000",
            ])
        elif framework == 'vue':
            lines.extend([
                "npm run serve  # or npm run dev",
            ])
        elif framework == 'angular':
            lines.extend([
                "ng serve",
            ])
        elif framework == 'svelte':
            lines.extend([
                "npm run dev",
            ])
        elif 'python' in languages:
            lines.extend([
                "# Flask/Django development server",
                "flask run  # or python manage.py runserver",
            ])
        else:
            lines.append("npm run dev  # or check package.json")

        lines.extend([
            "```",
            "",
            "### View in browser",
            "",
            "Open your browser to:",
            "- Development: http://localhost:3000 (or 5173 for Vite)",
            "- Check terminal output for the actual port",
            "",
        ])

        return lines

    def _quick_examples_library(self, project_type: ProjectType, pkg_name: str, languages: set) -> list:
        """Quick examples for library projects."""
        lines = [
            "### Check your installation",
            "",
            "```bash",
        ]

        if 'python' in languages:
            lines.extend([
                f"python -c \"import {pkg_name}; print('OK')\"",
            ])
        elif 'javascript' in languages or 'typescript' in languages:
            lines.extend([
                f"node -e \"require('{pkg_name}'); console.log('OK')\"",
            ])
        elif 'go' in languages:
            lines.append("go build ./...")
        elif 'rust' in languages:
            lines.append("cargo build")

        lines.extend([
            "```",
            "",
            "### Run the tests",
            "",
            "```bash",
        ])

        if 'python' in languages:
            lines.append("pytest  # or python -m pytest")
        elif 'javascript' in languages or 'typescript' in languages:
            lines.append("npm test")
        elif 'go' in languages:
            lines.append("go test ./...")
        elif 'rust' in languages:
            lines.append("cargo test")
        else:
            lines.append("# Check README for test command")

        lines.extend([
            "```",
            "",
        ])

        return lines

    def _quick_examples_microservice(self, project_type: ProjectType, pkg_name: str, languages: set) -> list:
        """Quick examples for microservice projects."""
        lines = [
            "### Build and run with Docker",
            "",
            "```bash",
            "# Build the container",
            "docker build -t " + pkg_name + " .",
            "",
            "# Run the container",
            "docker run -p 8080:8080 " + pkg_name,
            "```",
            "",
            "### Run locally (without Docker)",
            "",
            "```bash",
        ]

        if 'python' in languages:
            lines.append("python -m " + pkg_name + "  # or check Dockerfile CMD")
        elif 'go' in languages:
            lines.append("go run main.go")
        elif 'javascript' in languages or 'typescript' in languages:
            lines.append("npm start")
        else:
            lines.append("# Check Dockerfile CMD for start command")

        lines.extend([
            "```",
            "",
        ])

        return lines

    def _quick_examples_generic(self, pkg_name: str, languages: set) -> list:
        """Generic quick examples for unknown project types."""
        lines = [
            "### Check your installation",
            "",
            "```bash",
        ]

        if 'python' in languages:
            lines.append(f"python -c \"import {pkg_name}; print('OK')\"")
        elif 'javascript' in languages or 'typescript' in languages:
            lines.append("npm test  # or node index.js")

        lines.extend([
            "```",
            "",
            "### Run the tests",
            "",
            "```bash",
        ])

        if 'python' in languages:
            lines.append("pytest  # or python -m pytest")
        elif 'javascript' in languages or 'typescript' in languages:
            lines.append("npm test")

        lines.extend([
            "```",
            "",
        ])

        return lines

    # ------------------------------------------------------------------------
    # Main Generation Methods
    # ------------------------------------------------------------------------

    def _generate_architecture(self) -> str:
        """Generate architecture documentation based on skill level."""
        lines = [
            "# Architecture Overview",
            "",
        ]

        # Add project description from metadata if available
        if self.metadata.description:
            if self._is_level('junior'):
                # Extended intro for junior level
                lines.extend([
                    self.metadata.description,
                    "",
                    "> **What is this?** This document explains how the codebase is organized,",
                    "> what each part does, and how they work together. Start here to understand",
                    "> the big picture before diving into the code.",
                    "",
                ])
            elif self._is_level('senior'):
                # Brief for senior
                lines.extend([
                    f"*{self.metadata.description}*",
                    "",
                ])
            else:
                # Mid - current behavior
                lines.extend([
                    self.metadata.description,
                    "",
                ])

        # Project Structure section (skip for senior)
        if not self._is_level('senior'):
            lines.extend([
                "## Project Structure",
                "",
            ])
            lines.extend(self._section_project_structure(as_code_block=True))
            lines.append("")

            # Junior: explain each directory
            if self._is_level('junior'):
                lines.append("**Directory purposes:**")
                lines.append("")
                dir_limit = {'junior': 999, 'mid': 10, 'senior': 5}[self.skill_level]
                dirs_to_show = sorted(self.structure['directories'].items())[:dir_limit]
                for dir_path, info in dirs_to_show:
                    if dir_path == '.':
                        continue
                    langs = ', '.join(info['languages'])
                    lines.append(f"- **{dir_path}/**: Contains {info['files']} {langs} files")
                lines.append("")

        # Key modules section
        lines.append("## Key Modules")
        lines.append("")

        # Determine class/method limits based on level
        class_limit = {'junior': 999, 'mid': 5, 'senior': 3}[self.skill_level]
        method_limit = {'junior': 999, 'mid': 5, 'senior': 2}[self.skill_level]

        for path, info in sorted(self.files.items()):
            if info.classes or (info.functions and len(info.functions) > 3):
                lines.append(f"### `{path}`")
                if info.description:
                    lines.append(f"{info.description}")
                lines.append("")

                if info.classes:
                    lines.append("**Classes:**")
                    for cls in info.classes[:class_limit]:
                        # Show methods for this class if available
                        class_methods = info.methods.get(cls, [])
                        if class_methods:
                            methods_to_show = class_methods[:method_limit]
                            methods_str = ', '.join(f"{m}()" for m in methods_to_show)
                            if len(class_methods) > method_limit:
                                methods_str += f", ... (+{len(class_methods) - method_limit} more)"
                            lines.append(f"- `{cls}`: {methods_str}")

                            # Junior: explain what the class does
                            if self._is_level('junior') and len(methods_to_show) > 0:
                                lines.append(f"  - *Primary methods: {', '.join(methods_to_show[:3])}*")
                        else:
                            lines.append(f"- `{cls}`")
                    lines.append("")

                if info.functions and not self._is_level('senior'):
                    # Only show module-level functions (not class methods)
                    all_methods = set()
                    for methods in info.methods.values():
                        all_methods.update(methods)
                    func_limit = {'junior': 999, 'mid': 5, 'senior': 0}[self.skill_level]
                    public_funcs = [f for f in info.functions
                                    if not f.startswith('_') and f not in all_methods][:func_limit]
                    if public_funcs:
                        lines.append("**Key functions:**")
                        for func in public_funcs:
                            lines.append(f"- `{func}()`")
                        lines.append("")

        # Entry points
        if self.entry_points:
            lines.append("## Entry Points")
            lines.append("")
            if self._is_level('junior'):
                lines.append("> **Tip:** Entry points are where the program starts running.")
                lines.append("> These files are good starting points for understanding the code flow.")
                lines.append("")
            for ep in self._level_limit(self.entry_points, junior=999, mid=5, senior=2):
                lines.append(f"- **{ep['path']}**: {ep['description']}")
            lines.append("")

        # Dependencies (from imports)
        lines.append("## Dependencies")
        lines.append("")
        lines.extend(self._section_dependencies())
        lines.append("")

        return '\n'.join(lines)

    def _generate_onboarding(self) -> str:
        """Generate onboarding guide for new developers based on skill level.

        Uses helper methods for each section to keep this method readable.
        Type-aware generation based on detected project type (CLI, API, webapp, library).
        """
        project_name = self.metadata.name or self.project_dir.resolve().name
        repo_url = self.metadata.repository or '<repo-url>'
        languages = set(self.structure['file_types'].keys())

        # Detect project type for type-aware documentation
        project_type = self._detect_project_type()

        # Detect CLI info (for CLI projects)
        cli_info = self._detect_cli_info() if project_type.primary == 'cli' else {
            'is_cli': False, 'cli_name': '', 'commands': [], 'has_subcommands': False
        }

        lines = [
            "# Developer Onboarding Guide",
            "",
        ]

        # Welcome/intro based on level
        if self.metadata.description:
            if self._is_level('junior'):
                lines.extend([
                    f"Welcome to **{project_name}**!",
                    "",
                    f"> {self.metadata.description}",
                    "",
                    "This guide will help you get set up and start contributing.",
                    "Follow each section in order for the best experience.",
                    "",
                ])
            elif self._is_level('senior'):
                lines.extend([
                    f"*{project_name}* - {self.metadata.description}",
                    "",
                ])
            else:
                lines.extend([
                    f"Welcome to **{project_name}**! {self.metadata.description}",
                    "",
                ])

        # Senior: minimal quick start and return early
        if self._is_level('senior'):
            lines.extend([
                "## Quick Start",
                "",
                "```bash",
                f"git clone {repo_url} && cd {project_name} && pip install -e .",
                "```",
                "",
                "See `CLAUDE.md` for architecture details and PR conventions.",
                "",
            ])
            return '\n'.join(lines)

        # Prerequisites
        lines.extend([
            "## Getting Started",
            "",
            "### Prerequisites",
            "",
        ])
        lines.extend(self._onboarding_prerequisites(languages))
        lines.append("")

        # Setup instructions
        lines.extend(self._onboarding_setup(languages, repo_url, project_name))

        # === CLI USAGE SECTION (new - right after setup) ===
        lines.extend(self._onboarding_usage(cli_info, project_name))

        # Project structure (moved after usage for better flow)
        lines.extend([
            "## Project Structure",
            "",
            "Here's how the codebase is organized:",
            "",
        ])
        # Use detailed=True for junior level to show individual file purposes
        lines.extend(self._section_project_structure(as_code_block=False, detailed=True))
        lines.append("")

        # Key files
        lines.extend([
            "## Key Files to Understand",
            "",
            "Start by reading these files to understand the codebase:",
            "",
        ])
        ep_limit = {'junior': 10, 'mid': 5, 'senior': 3}[self.skill_level]
        for i, ep in enumerate(self.entry_points[:ep_limit], 1):
            lines.append(f"{i}. `{ep['path']}` - {ep['description']}")
        lines.append("")

        # Junior: Quick examples based on project type
        if self._is_level('junior') and not cli_info['is_cli']:
            lines.extend(self._onboarding_quick_examples(project_type, project_name, languages))

        # Development workflow
        lines.extend(self._onboarding_workflow())

        # Common pitfalls (junior only - returns empty list for others)
        lines.extend(self._onboarding_pitfalls())

        # Getting help
        lines.extend([
            "## Getting Help",
            "",
            "- Check existing issues for similar problems",
            "- Read the architecture docs for system design",
            "- Ask questions in discussions/chat",
            "",
        ])

        return '\n'.join(lines)

    def _generate_api(self) -> str:
        """Generate API reference documentation based on skill level."""
        lines = [
            "# API Reference",
            "",
        ]

        # Add project info if available
        if self.metadata.name:
            lines.extend([
                f"API documentation for `{self.metadata.name}`",
                "",
            ])
            if self.metadata.version:
                lines.extend([
                    f"Version: {self.metadata.version}",
                    "",
                ])

        # Junior: Add intro explanation
        if self._is_level('junior'):
            lines.extend([
                "> **How to read this:** Each module lists its classes and functions.",
                "> Classes show their methods. Start with the main classes to understand the API.",
                "",
            ])

        # Group by directory
        by_dir = {}
        for path, info in self.files.items():
            dir_path = str(Path(path).parent) or 'root'
            if dir_path not in by_dir:
                by_dir[dir_path] = []
            by_dir[dir_path].append((path, info))

        # Method limit based on level
        method_limit = {'junior': 999, 'mid': 20, 'senior': 5}[self.skill_level]

        for dir_path in sorted(by_dir.keys()):
            if dir_path != 'root':
                lines.append(f"## {dir_path}")
                lines.append("")

            for path, info in sorted(by_dir[dir_path]):
                if not info.classes and not info.functions:
                    continue

                lines.append(f"### `{Path(path).name}`")
                lines.append("")

                if info.description:
                    lines.append(info.description)
                    lines.append("")

                if info.classes:
                    lines.append("#### Classes")
                    lines.append("")
                    for cls in info.classes:
                        # Show class with its methods
                        class_methods = info.methods.get(cls, [])
                        if class_methods:
                            lines.append(f"**{cls}**")
                            lines.append("")

                            # Filter methods based on level
                            if self._is_level('junior'):
                                # Show all methods including private
                                methods_to_show = class_methods[:method_limit]
                            elif self._is_level('senior'):
                                # Only public methods
                                methods_to_show = [m for m in class_methods
                                                   if not m.startswith('_')][:method_limit]
                            else:
                                # Mid: public + special methods
                                methods_to_show = [m for m in class_methods
                                                   if not m.startswith('_') or m.startswith('__')][:method_limit]

                            for method in methods_to_show:
                                lines.append(f"- `{method}()`")

                            if len(class_methods) > len(methods_to_show):
                                lines.append(f"- *... and {len(class_methods) - len(methods_to_show)} more*")
                            lines.append("")
                        else:
                            lines.append(f"- **{cls}**")
                    if not any(info.methods.get(cls) for cls in info.classes):
                        lines.append("")

                if info.functions:
                    # Only show module-level functions (not class methods)
                    all_methods = set()
                    for methods in info.methods.values():
                        all_methods.update(methods)

                    if self._is_level('junior'):
                        # Show all functions including private with explanation
                        funcs_to_show = [f for f in info.functions if f not in all_methods]
                    else:
                        # Public only
                        funcs_to_show = [f for f in info.functions
                                         if not f.startswith('_') and f not in all_methods]

                    if funcs_to_show:
                        lines.append("#### Functions")
                        lines.append("")
                        for func in funcs_to_show[:method_limit]:
                            if self._is_level('junior') and func.startswith('_'):
                                lines.append(f"- `{func}()` *(internal)*")
                            else:
                                lines.append(f"- `{func}()`")
                        lines.append("")

        return '\n'.join(lines)

    def _generate_readme(self) -> str:
        """Generate a README file using project metadata based on skill level."""
        # Use metadata name, falling back to directory name
        project_name = self.metadata.name or self.project_dir.resolve().name

        lines = [
            f"# {project_name}",
            "",
        ]

        # Add badges if we have metadata (skip for senior - minimal)
        if not self._is_level('senior'):
            badges = []
            if self.metadata.version:
                badges.append(f"![Version](https://img.shields.io/badge/version-{self.metadata.version}-blue)")
            if self.metadata.license:
                badges.append(f"![License](https://img.shields.io/badge/license-{self.metadata.license}-green)")
            if self.metadata.python_requires:
                py_version = self.metadata.python_requires.replace('>=', '').replace('>', '').strip()
                badges.append(f"![Python](https://img.shields.io/badge/python-{py_version}+-yellow)")

            if badges:
                lines.append(' '.join(badges))
                lines.append("")

        lines.extend([
            "## Overview",
            "",
        ])

        # Use actual description with level-specific formatting
        if self.metadata.description:
            if self._is_level('junior'):
                lines.extend([
                    self.metadata.description,
                    "",
                    "### What does this project do?",
                    "",
                    "This project provides tools for:",
                    "",
                ])
                # Add key concepts if available
                if self.key_concepts:
                    for concept in self.key_concepts[:5]:
                        lines.append(f"- **{concept}**")
                    lines.append("")
            elif self._is_level('senior'):
                lines.append(f"*{self.metadata.description}*")
            else:
                lines.append(self.metadata.description)
        else:
            lines.append("<!-- Add project description here -->")
        lines.append("")

        lines.extend([
            "## Installation",
            "",
        ])

        languages = set(self.structure['file_types'].keys())
        repo_url = self.metadata.repository or '<repo-url>'

        if 'python' in languages:
            install_name = self.metadata.name or '<package-name>'

            if self._is_level('senior'):
                # Senior: quickest method only
                lines.extend([
                    "```bash",
                    f"pip install git+{repo_url}" if self.metadata.repository else f"pip install {install_name}",
                    "```",
                    "",
                ])
            elif self._is_level('junior'):
                # Junior: multiple methods with explanation
                lines.extend([
                    "### Quick Install",
                    "",
                ])
                if self.metadata.repository:
                    lines.extend([
                        "```bash",
                        f"pip install git+{self.metadata.repository}",
                        "```",
                        "",
                        "### Development Install (recommended for contributors)",
                        "",
                        "If you want to modify the code:",
                        "",
                        "```bash",
                        "# 1. Clone the repository",
                        f"git clone {self.metadata.repository}",
                        f"cd {project_name}",
                        "",
                        "# 2. Create a virtual environment (recommended)",
                        "python -m venv venv",
                        "source venv/bin/activate  # On Windows: venv\\Scripts\\activate",
                        "",
                        "# 3. Install in development mode",
                        "pip install -e .",
                        "```",
                        "",
                    ])
                else:
                    lines.extend([
                        "```bash",
                        f"pip install {install_name}",
                        "```",
                        "",
                    ])
            else:
                # Mid: current behavior
                if self.metadata.repository:
                    lines.extend([
                        "```bash",
                        f"pip install git+{self.metadata.repository}",
                        "```",
                        "",
                        "Or for development:",
                        "",
                        "```bash",
                        f"git clone {self.metadata.repository}",
                        f"cd {project_name}",
                        "pip install -e .",
                        "```",
                        "",
                    ])
                else:
                    lines.extend([
                        "```bash",
                        f"pip install {install_name}",
                        "```",
                        "",
                    ])
        elif 'javascript' in languages or 'typescript' in languages:
            install_name = self.metadata.name or '<package-name>'
            lines.extend([
                "```bash",
                f"npm install {install_name}",
                "```",
                "",
            ])

        # Junior: Add Quick Start section
        if self._is_level('junior'):
            lines.extend([
                "## Quick Start",
                "",
                "Here's a simple example to get you started:",
                "",
                "```python",
                f"from {project_name.replace('-', '_')} import Agent",
                "",
                "# Create an instance",
                "agent = Agent()",
                "",
                "# Use the main functionality",
                "# (see documentation for more details)",
                "```",
                "",
            ])

        lines.extend([
            "## Usage",
            "",
            "<!-- Add usage examples here -->",
            "",
            "## Documentation",
            "",
        ])

        # Highlight architecture for junior level
        if self._is_level('junior'):
            lines.extend([
                "**New here? Start with these:**",
                "",
                "- [Onboarding Guide](docs/onboarding.md) - Setup and first steps",
                "- [Architecture](docs/architecture.md) - How the code is organized",
                "- [API Reference](docs/api.md) - All classes and functions",
                "",
            ])
        else:
            lines.extend([
                "- [Architecture](docs/architecture.md)",
                "- [Onboarding](docs/onboarding.md)",
                "- [API Reference](docs/api.md)",
                "",
            ])

        lines.extend([
            "## Contributing",
            "",
            "Contributions welcome! Please read the onboarding guide first.",
            "",
            "## License",
            "",
        ])

        # Use actual license or placeholder
        if self.metadata.license:
            lines.append(f"This project is licensed under the {self.metadata.license} License.")
        else:
            lines.append("<!-- Add license info -->")
        lines.append("")

        return '\n'.join(lines)


# ============================================================================
# CLI Integration
# ============================================================================

def cmd_docs(args):
    """Handle docs CLI commands."""
    # Get skill level from args (defaults to 'mid')
    skill_level = getattr(args, 'level', 'mid')

    agent = DocsAgent(
        project_dir=Path(args.path or '.'),
        output_dir=Path(args.output) if hasattr(args, 'output') and args.output else None,
        skill_level=skill_level,
    )

    if args.docs_command == 'analyze':
        force = getattr(args, 'force', False)
        if force:
            print("Analyzing codebase (forced full re-analysis)...")
        else:
            print("Analyzing codebase...")
        verbose = getattr(args, 'verbose', False)
        result = agent.analyze(verbose=verbose, force=force)
        print("\n✓ Analysis complete:")
        print(f"  Total files: {result['total_files']}")
        if result.get('files_cached', 0) > 0:
            print(f"  Cached: {result['files_cached']} (unchanged)")
            print(f"  Analyzed: {result['files_analyzed']} (new/changed)")
        else:
            print(f"  Analyzed: {result['files_analyzed']}")
        if result.get('files_removed', 0) > 0:
            print(f"  Removed: {result['files_removed']} (deleted files)")
        print(f"  Lines: {result['total_lines']:,}")
        print(f"  Directories: {result['directories']}")
        print(f"  Entry points: {result['entry_points']}")

    elif args.docs_command == 'generate':
        doc_type = args.type or 'architecture'
        level_msg = f" ({skill_level} level)" if skill_level != 'mid' else ""
        print(f"Generating {doc_type} documentation{level_msg}...")

        agent.analyze()
        output_path = Path(args.output) if hasattr(args, 'output') and args.output else None
        content = agent.generate(doc_type, output_path)

        # Calculate actual path (generate() handles the suffix)
        if output_path:
            actual_path = output_path
        else:
            suffix = f"-{skill_level}" if skill_level != 'mid' else ""
            actual_path = agent.output_dir / f"{doc_type}{suffix}.md"
        print(f"✓ Generated: {actual_path}")
        print(f"  Lines: {len(content.split(chr(10)))}")

    elif args.docs_command == 'all':
        level_msg = f" ({skill_level} level)" if skill_level != 'mid' else ""
        print(f"Generating all documentation{level_msg}...")
        agent.analyze(verbose=True)

        suffix = f"-{skill_level}" if skill_level != 'mid' else ""
        for doc_type in ['architecture', 'onboarding', 'api']:
            content = agent.generate(doc_type)
            path = agent.output_dir / f"{doc_type}{suffix}.md"
            print(f"  ✓ {path}")

        print(f"\n✓ All docs generated in {agent.output_dir}/")

    elif args.docs_command == 'context':
        # Output structured context for Claude Code to analyze
        agent.analyze()
        context = agent.generate_context()
        print(context)

    else:
        print("Usage:")
        print("  claudia docs analyze                    Analyze codebase structure")
        print("  claudia docs generate [--type X] [-L Y] Generate documentation")
        print("  claudia docs context                    Output structured context for AI")
        print("  claudia docs all [-L Y]                 Generate all doc types")
        print("\nDoc types: architecture, onboarding, api, readme, insights")
        print("Levels: junior (verbose), mid (balanced), senior (minimal)")

    return 0
