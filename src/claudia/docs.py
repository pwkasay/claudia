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

import json
import os
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


@dataclass
class DocsAgent:
    """
    Documentation generator that analyzes codebases and produces
    human-centered documentation.
    """

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

    def __post_init__(self):
        if self.project_dir is None:
            self.project_dir = Path('.')
        else:
            self.project_dir = Path(self.project_dir)

        if self.output_dir is None:
            self.output_dir = self.project_dir / 'docs'

        if self.state_file is None:
            self.state_file = self.project_dir / '.agent-state' / 'docs-state.json'

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

    def analyze(self, verbose: bool = False) -> dict:
        """
        Analyze the codebase structure.

        Returns a summary of what was found.
        """
        self.files = {}
        self.structure = {
            'directories': {},
            'file_types': {},
            'total_lines': 0,
        }
        self.entry_points = []
        self.key_concepts = []

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

        for pattern in source_patterns:
            for file_path in self.project_dir.glob(pattern):
                # Skip ignored paths
                rel_path = str(file_path.relative_to(self.project_dir))
                if any(self._match_pattern(rel_path, p) for p in ignore_patterns):
                    continue

                info = self._analyze_file(file_path)
                if info:
                    self.files[rel_path] = info
                    if verbose:
                        print(f"  Analyzed: {rel_path}")

        # Build structure summary
        self._build_structure()

        # Find entry points
        self._find_entry_points()

        # Extract key concepts
        self._extract_key_concepts()

        # Save state
        self._save_state()

        return {
            'files_analyzed': len(self.files),
            'total_lines': self.structure['total_lines'],
            'directories': len(self.structure['directories']),
            'entry_points': len(self.entry_points),
            'key_concepts': len(self.key_concepts),
        }

    def _match_pattern(self, path: str, pattern: str) -> bool:
        """Simple glob-style pattern matching."""
        import fnmatch
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
            elif info.language in ('javascript', 'typescript'):
                info.imports = self._extract_js_imports(content)
                info.exports = self._extract_js_exports(content)
                info.functions = self._extract_js_functions(content)
                info.classes = self._extract_js_classes(content)

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
            '.go': 'go',
            '.rs': 'rust',
            '.java': 'java',
            '.rb': 'ruby',
            '.c': 'c',
            '.cpp': 'cpp',
            '.h': 'c',
            '.hpp': 'cpp',
        }
        return ext_map.get(file_path.suffix.lower(), 'unknown')

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
        return imports[:20]  # Limit

    def _extract_python_functions(self, content: str) -> list:
        """Extract Python function names."""
        functions = []
        for match in re.finditer(r'^def\s+(\w+)\s*\(', content, re.MULTILINE):
            name = match.group(1)
            if not name.startswith('_') or name.startswith('__'):
                functions.append(name)
        return functions[:30]

    def _extract_python_classes(self, content: str) -> list:
        """Extract Python class names."""
        classes = []
        for match in re.finditer(r'^class\s+(\w+)', content, re.MULTILINE):
            classes.append(match.group(1))
        return classes[:20]

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
        return {cls: meths[:20] for cls, meths in methods.items()}

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
        """Extract JavaScript/TypeScript imports."""
        imports = []
        for match in re.finditer(r"(?:import|require)\s*\(?['\"]([^'\"]+)['\"]", content):
            module = match.group(1)
            if not module.startswith('.'):
                module = module.split('/')[0]
                if module and module not in imports:
                    imports.append(module)
        return imports[:20]

    def _extract_js_exports(self, content: str) -> list:
        """Extract JavaScript/TypeScript exports."""
        exports = []
        for match in re.finditer(r'export\s+(?:default\s+)?(?:const|let|var|function|class)\s+(\w+)', content):
            exports.append(match.group(1))
        return exports[:20]

    def _extract_js_functions(self, content: str) -> list:
        """Extract JavaScript function names."""
        functions = []
        patterns = [
            r'function\s+(\w+)\s*\(',
            r'const\s+(\w+)\s*=\s*(?:async\s*)?\(',
            r'(\w+)\s*:\s*(?:async\s*)?\(',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                name = match.group(1)
                if name and name not in functions:
                    functions.append(name)
        return functions[:30]

    def _extract_js_classes(self, content: str) -> list:
        """Extract JavaScript class names."""
        classes = []
        for match in re.finditer(r'class\s+(\w+)', content):
            classes.append(match.group(1))
        return classes[:20]

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
                        'description': info.description or f"Executable module",
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
        self.key_concepts = list(set(all_classes))[:15]

    def _save_state(self):
        """Save analysis state for incremental updates."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        state = {
            'analyzed_at': datetime.now(timezone.utc).isoformat(),
            'files_count': len(self.files),
            'total_lines': self.structure['total_lines'],
            'file_hashes': {
                path: f"{info.size}:{info.lines}"
                for path, info in self.files.items()
            },
        }

        self.state_file.write_text(json.dumps(state, indent=2))

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

            # Directory overview
            lines.append("```")
            dirs_to_show = self._level_limit(
                sorted(self.structure['directories'].items()),
                junior=999, mid=10, senior=5
            )
            for dir_path, info in dirs_to_show:
                if dir_path == '.':
                    continue
                indent = "  " * dir_path.count('/')
                langs = ', '.join(info['languages'])
                lines.append(f"{indent}{dir_path}/ ({info['files']} files, {langs})")
            lines.append("```")
            lines.append("")

            # Junior: explain each directory
            if self._is_level('junior'):
                lines.append("**Directory purposes:**")
                lines.append("")
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

        all_imports = set()
        for info in self.files.values():
            all_imports.update(info.imports)

        # Filter to external dependencies (stdlib already filtered in extraction)
        internal_modules = {Path(p).stem for p in self.files.keys()}
        # Also filter out internal package names from directory structure
        internal_packages = set()
        for p in self.files.keys():
            parts = Path(p).parts
            for part in parts:
                # Add each directory component as potential internal package
                clean_part = part.replace('.py', '')
                if clean_part:
                    internal_packages.add(clean_part)

        # Also add the project name from metadata as internal
        if self.metadata.name:
            internal_packages.add(self.metadata.name)

        external = sorted(all_imports - internal_modules - internal_packages)[:20]

        if external:
            if self._is_level('junior'):
                lines.append("External packages this project uses:")
                lines.append("")
            for imp in external:
                lines.append(f"- `{imp}`")
        else:
            lines.append("Standard library only (no external dependencies).")
        lines.append("")

        return '\n'.join(lines)

    def _generate_onboarding(self) -> str:
        """Generate onboarding guide for new developers based on skill level."""
        project_name = self.metadata.name or self.project_dir.resolve().name

        lines = [
            "# Developer Onboarding Guide",
            "",
        ]

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

        # Senior: minimal setup, just the essentials
        if self._is_level('senior'):
            repo_url = self.metadata.repository or '<repo-url>'
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

        lines.extend([
            "## Getting Started",
            "",
            "### Prerequisites",
            "",
        ])

        # Detect language and add setup instructions
        languages = set(self.structure['file_types'].keys())

        # Use actual Python version requirement if available
        python_version = self.metadata.python_requires or "3.10+"
        python_version = python_version.replace('>=', '').strip()
        if not python_version.endswith('+'):
            python_version += '+'

        # Use actual repo URL if available
        repo_url = self.metadata.repository or '<repo-url>'

        if 'python' in languages:
            if self._is_level('junior'):
                lines.extend([
                    f"- **Python {python_version}** - [Download Python](https://python.org/downloads/)",
                    "  - Verify with: `python --version` or `python3 --version`",
                    "- **pip** - Usually comes with Python. Verify with: `pip --version`",
                    "- **Git** - [Download Git](https://git-scm.com/downloads)",
                    "",
                ])
            else:
                lines.extend([
                    f"- Python {python_version}",
                    "- pip or pipenv",
                    "",
                ])

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

            # Junior: Add troubleshooting tips
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
            if self._is_level('junior'):
                lines.extend([
                    "- **Node.js 18+** - [Download Node.js](https://nodejs.org/)",
                    "  - Verify with: `node --version`",
                    "- **npm** - Comes with Node.js. Verify with: `npm --version`",
                    "",
                ])
            else:
                lines.extend([
                    "- Node.js 18+",
                    "- npm or yarn",
                    "",
                ])

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

        # Project structure orientation (skip for senior, already returned)
        dir_limit = {'junior': 999, 'mid': 10, 'senior': 5}[self.skill_level]
        lines.extend([
            "## Project Structure",
            "",
            "Here's how the codebase is organized:",
            "",
        ])

        for dir_path, info in sorted(self.structure['directories'].items())[:dir_limit]:
            if dir_path == '.':
                lines.append(f"- **Root**: Configuration files, entry points")
            else:
                if self._is_level('junior'):
                    langs = ', '.join(info['languages'])
                    lines.append(f"- **{dir_path}/**: {info['files']} {langs} files")
                else:
                    lines.append(f"- **{dir_path}/**: {info['files']} files")

        lines.append("")

        # Key files to understand
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

        # Junior: Add Quick Examples section
        if self._is_level('junior'):
            lines.extend([
                "## Quick Examples",
                "",
                "Here are some common tasks to try after setup:",
                "",
                "### Check your installation",
                "",
                "```bash",
                f"# Make sure {project_name} is installed",
            ])
            if 'python' in languages:
                lines.extend([
                    f"python -c \"import {project_name.replace('-', '_')}; print('OK')\"",
                ])
            lines.extend([
                "```",
                "",
                "### Run the tests",
                "",
                "```bash",
                "# If tests exist in the project",
            ])
            if 'python' in languages:
                lines.append("pytest  # or python -m pytest")
            elif 'javascript' in languages or 'typescript' in languages:
                lines.append("npm test")
            lines.extend([
                "```",
                "",
            ])

        # Development workflow
        lines.extend([
            "## Development Workflow",
            "",
        ])

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

        # Junior: Add Common Pitfalls section
        if self._is_level('junior'):
            lines.extend([
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
            ])

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
        print("Analyzing codebase...")
        result = agent.analyze(verbose=args.verbose if hasattr(args, 'verbose') else False)
        print(f"\n✓ Analysis complete:")
        print(f"  Files: {result['files_analyzed']}")
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

    else:
        print("Usage:")
        print("  claudia docs analyze                    Analyze codebase structure")
        print("  claudia docs generate [--type X] [-L Y] Generate documentation")
        print("  claudia docs all [-L Y]                 Generate all doc types")
        print("\nDoc types: architecture, onboarding, api, readme")
        print("Levels: junior (verbose), mid (balanced), senior (minimal)")

    return 0
