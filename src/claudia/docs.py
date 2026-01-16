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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


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

    def __post_init__(self):
        if self.project_dir is None:
            self.project_dir = Path('.')
        else:
            self.project_dir = Path(self.project_dir)

        if self.output_dir is None:
            self.output_dir = self.project_dir / 'docs'

        if self.state_file is None:
            self.state_file = self.project_dir / '.agent-state' / 'docs-state.json'

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

    def _extract_python_imports(self, content: str) -> list:
        """Extract Python imports."""
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

    def _extract_python_docstring(self, content: str) -> str:
        """Extract module docstring."""
        match = re.match(r'^[\s]*["\'][\"\'][\"\'](.+?)["\'][\"\'][\"\']', content, re.DOTALL)
        if match:
            return match.group(1).strip()[:200]
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
            output_path: Where to write the output (default: docs/<type>.md)

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

        # Write to file
        if output_path is None:
            output_path = self.output_dir / f"{doc_type}.md"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)

        return content

    def _generate_architecture(self) -> str:
        """Generate architecture documentation."""
        lines = [
            "# Architecture Overview",
            "",
            "## Project Structure",
            "",
        ]

        # Directory overview
        lines.append("```")
        for dir_path, info in sorted(self.structure['directories'].items()):
            if dir_path == '.':
                continue
            indent = "  " * dir_path.count('/')
            langs = ', '.join(info['languages'])
            lines.append(f"{indent}{dir_path}/ ({info['files']} files, {langs})")
        lines.append("```")
        lines.append("")

        # Key modules
        lines.append("## Key Modules")
        lines.append("")

        for path, info in sorted(self.files.items()):
            if info.classes or (info.functions and len(info.functions) > 3):
                lines.append(f"### `{path}`")
                if info.description:
                    lines.append(f"{info.description}")
                lines.append("")

                if info.classes:
                    lines.append("**Classes:**")
                    for cls in info.classes[:5]:
                        lines.append(f"- `{cls}`")
                    lines.append("")

                if info.functions:
                    public_funcs = [f for f in info.functions if not f.startswith('_')][:5]
                    if public_funcs:
                        lines.append("**Key functions:**")
                        for func in public_funcs:
                            lines.append(f"- `{func}()`")
                        lines.append("")

        # Entry points
        if self.entry_points:
            lines.append("## Entry Points")
            lines.append("")
            for ep in self.entry_points:
                lines.append(f"- **{ep['path']}**: {ep['description']}")
            lines.append("")

        # Dependencies (from imports)
        lines.append("## Dependencies")
        lines.append("")

        all_imports = set()
        for info in self.files.values():
            all_imports.update(info.imports)

        # Filter to external dependencies
        internal_modules = {Path(p).stem for p in self.files.keys()}
        external = sorted(all_imports - internal_modules)[:20]

        if external:
            for imp in external:
                lines.append(f"- `{imp}`")
        else:
            lines.append("No external dependencies detected.")
        lines.append("")

        return '\n'.join(lines)

    def _generate_onboarding(self) -> str:
        """Generate onboarding guide for new developers."""
        lines = [
            "# Developer Onboarding Guide",
            "",
            "## Getting Started",
            "",
            "### Prerequisites",
            "",
        ]

        # Detect language and add setup instructions
        languages = set(self.structure['file_types'].keys())

        if 'python' in languages:
            lines.extend([
                "- Python 3.10+",
                "- pip or pipenv",
                "",
                "### Setup",
                "",
                "```bash",
                "# Clone the repository",
                "git clone <repo-url>",
                "cd <project>",
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

        if 'javascript' in languages or 'typescript' in languages:
            lines.extend([
                "- Node.js 18+",
                "- npm or yarn",
                "",
                "### Setup",
                "",
                "```bash",
                "# Clone and install",
                "git clone <repo-url>",
                "cd <project>",
                "npm install",
                "```",
                "",
            ])

        # Project structure orientation
        lines.extend([
            "## Project Structure",
            "",
            "Here's how the codebase is organized:",
            "",
        ])

        for dir_path, info in sorted(self.structure['directories'].items())[:10]:
            if dir_path == '.':
                lines.append(f"- **Root**: Configuration files, entry points")
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

        for ep in self.entry_points[:5]:
            lines.append(f"1. `{ep['path']}` - {ep['description']}")

        lines.append("")

        # Development workflow
        lines.extend([
            "## Development Workflow",
            "",
            "1. Create a feature branch: `git checkout -b feature/my-feature`",
            "2. Make your changes",
            "3. Run tests (if available)",
            "4. Submit a pull request",
            "",
            "## Getting Help",
            "",
            "- Check existing issues for similar problems",
            "- Read the architecture docs for system design",
            "- Ask questions in discussions/chat",
            "",
        ])

        return '\n'.join(lines)

    def _generate_api(self) -> str:
        """Generate API reference documentation."""
        lines = [
            "# API Reference",
            "",
        ]

        # Group by directory
        by_dir = {}
        for path, info in self.files.items():
            dir_path = str(Path(path).parent) or 'root'
            if dir_path not in by_dir:
                by_dir[dir_path] = []
            by_dir[dir_path].append((path, info))

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
                        lines.append(f"- **{cls}**")
                    lines.append("")

                if info.functions:
                    public_funcs = [f for f in info.functions if not f.startswith('_')]
                    if public_funcs:
                        lines.append("#### Functions")
                        lines.append("")
                        for func in public_funcs:
                            lines.append(f"- `{func}()`")
                        lines.append("")

        return '\n'.join(lines)

    def _generate_readme(self) -> str:
        """Generate a README file."""
        project_name = self.project_dir.resolve().name

        lines = [
            f"# {project_name.title()}",
            "",
            "## Overview",
            "",
            "<!-- Add project description here -->",
            "",
            "## Installation",
            "",
        ]

        languages = set(self.structure['file_types'].keys())

        if 'python' in languages:
            lines.extend([
                "```bash",
                "pip install <package-name>",
                "```",
                "",
            ])
        elif 'javascript' in languages or 'typescript' in languages:
            lines.extend([
                "```bash",
                "npm install <package-name>",
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
            "- [Architecture](docs/architecture.md)",
            "- [Onboarding](docs/onboarding.md)",
            "- [API Reference](docs/api.md)",
            "",
            "## Contributing",
            "",
            "Contributions welcome! Please read the onboarding guide first.",
            "",
            "## License",
            "",
            "<!-- Add license info -->",
            "",
        ])

        return '\n'.join(lines)


# ============================================================================
# CLI Integration
# ============================================================================

def cmd_docs(args):
    """Handle docs CLI commands."""
    agent = DocsAgent(
        project_dir=Path(args.path or '.'),
        output_dir=Path(args.output) if hasattr(args, 'output') and args.output else None,
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
        print(f"Generating {doc_type} documentation...")

        agent.analyze()
        output_path = Path(args.output) if hasattr(args, 'output') and args.output else None
        content = agent.generate(doc_type, output_path)

        actual_path = output_path or agent.output_dir / f"{doc_type}.md"
        print(f"✓ Generated: {actual_path}")
        print(f"  Lines: {len(content.split(chr(10)))}")

    elif args.docs_command == 'all':
        print("Generating all documentation...")
        agent.analyze(verbose=True)

        for doc_type in ['architecture', 'onboarding', 'api']:
            content = agent.generate(doc_type)
            path = agent.output_dir / f"{doc_type}.md"
            print(f"  ✓ {path}")

        print(f"\n✓ All docs generated in {agent.output_dir}/")

    else:
        print("Usage:")
        print("  claudia docs analyze              Analyze codebase structure")
        print("  claudia docs generate [--type X]  Generate documentation")
        print("  claudia docs all                  Generate all doc types")
        print("\nDoc types: architecture, onboarding, api, readme")

    return 0
