#!/usr/bin/env python3
"""Fail-closed text contract for the deliberately small CI workflow.

This is not a general YAML parser. Only the reviewed YAML layout below is
accepted (blank lines and standalone comments are ignored). Unknown keys,
actions and shell commands fail, including mutation/scientific commands or
error suppression. Intentional workflow changes must update this contract.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/project-state-consistency.yml'
REQUIRED_COMMANDS = (
    'python3 tools/validate_project_state.py',
    'python3 tools/validate_project_state.py --check-status',
    'python3 tests/test_project_state.py',
    'python3 tests/test_recovery_state.py',
    'python3 tests/test_backlog_evidence.py',
)
EXPECTED = """name: Project state consistency
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  project-state-consistency:
    name: Project state consistency
    runs-on: ubuntu-latest
    env:
      PYTHONDONTWRITEBYTECODE: '1'
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Validate project state, recovery and backlog
        shell: bash
        run: |
""" + ''.join(f'          {command}\n' for command in REQUIRED_COMMANDS) + (
    '          python3 tests/test_project_state_ci_contract.py\n'
)


def significant_lines(text):
    return [line.rstrip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def validate_contract(text):
    for forbidden in ('pull_request_target', 'continue-on-error', '|| true', 'secrets.'):
        if forbidden in text:
            raise AssertionError(f'Forbidden workflow text: {forbidden}')
    if significant_lines(text) != significant_lines(EXPECTED):
        raise AssertionError('Workflow differs from the reviewed read-only CI allowlist')


class ProjectStateCIContractTests(unittest.TestCase):
    def test_repository_workflow(self):
        self.assertTrue(WORKFLOW.is_file(), str(WORKFLOW))
        validate_contract(WORKFLOW.read_text(encoding='utf-8'))

    def test_rejects_unsafe_or_incomplete_workflows(self):
        mutations = [
            EXPECTED.replace('pull_request:', 'pull_request_target:'),
            EXPECTED.replace('  pull_request:\n', ''),
            EXPECTED.replace('branches: [main]', 'branches: [develop]'),
            EXPECTED.replace('  push:', '  push:\n    paths: [docs/**]'),
            EXPECTED.replace('contents: read', 'contents: write'),
            EXPECTED.replace('contents: read', 'contents: read\n  issues: write'),
            EXPECTED.replace('    runs-on:', '    if: false\n    runs-on:'),
            EXPECTED.replace('shell: bash', 'shell: bash {0}'),
            EXPECTED.replace('        run: |', '        continue-on-error: true\n        run: |'),
            EXPECTED.replace('persist-credentials: false', 'persist-credentials: true'),
        ]
        mutations.extend(EXPECTED.replace(f'          {command}\n', '')
                         for command in REQUIRED_COMMANDS)
        for command in (
            'gh issue close 346', 'gh pr create', 'git push',
            'gh api -X POST repos/owner/repo/issues',
            'python3 training/run.py', 'python3 analysis/run.py',
            'python3 reproducibility/run.py', 'pip install pyyaml',
            'echo "${{ secrets.CUSTOM_TOKEN }}"', 'exit 0', 'set +e',
        ):
            mutations.append(EXPECTED.replace('        run: |\n',
                                             f'        run: |\n          {command}\n'))
        for suffix in (' || true', ' || exit 0', '; true', ' &'):
            mutations.append(EXPECTED.replace(REQUIRED_COMMANDS[0] + '\n',
                                             REQUIRED_COMMANDS[0] + suffix + '\n'))
        for index, text in enumerate(mutations):
            with self.subTest(mutation=index):
                with self.assertRaises(AssertionError):
                    validate_contract(text)


if __name__ == '__main__':
    unittest.main()
