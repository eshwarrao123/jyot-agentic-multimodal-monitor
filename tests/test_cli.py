"""Tests for CLI argument parsing."""

import pytest
from pathlib import Path
import tempfile

from jyot_monitor.cli import create_parser, validate_run_args, CLIError


def test_parser_creation():
    """Test parser is created with all required commands."""
    parser = create_parser()
    
    # Test version is accessible
    assert parser.prog == "jyot_monitor"


def test_run_live_mode():
    """Test parsing run --live command."""
    parser = create_parser()
    
    with tempfile.NamedTemporaryFile(suffix=".yaml") as f:
        sources_path = Path(f.name)
        
        args = parser.parse_args([
            "run",
            "--live",
            "--sources", str(sources_path),
            "--top-n", "5"
        ])
        
        assert args.command == "run"
        assert args.live is True
        assert args.replay is None
        assert args.top_n == 5


def test_run_replay_mode():
    """Test parsing run --replay command."""
    parser = create_parser()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_dir = Path(tmpdir)
        
        args = parser.parse_args([
            "run",
            "--replay", str(fixtures_dir),
            "--top-n", "10",
            "--budget-usd", "2.50"
        ])
        
        assert args.command == "run"
        assert args.live is False
        assert args.replay == fixtures_dir
        assert args.top_n == 10
        assert args.budget_usd == 2.50


def test_run_fault_injection():
    """Test fault injection flag."""
    parser = create_parser()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        args = parser.parse_args([
            "run",
            "--replay", tmpdir,
            "--fault-injection"
        ])
        
        assert args.fault_injection is True


def test_eval_command():
    """Test parsing eval command."""
    parser = create_parser()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        gold_dir = Path(tmpdir)
        
        args = parser.parse_args([
            "eval",
            "--gold", str(gold_dir)
        ])
        
        assert args.command == "eval"
        assert args.gold == gold_dir


def test_approve_command():
    """Test parsing approve command."""
    parser = create_parser()
    
    args = parser.parse_args(["approve", "prop_123"])
    
    assert args.command == "approve"
    assert args.proposal_id == "prop_123"


def test_reject_command():
    """Test parsing reject command."""
    parser = create_parser()
    
    args = parser.parse_args(["reject", "prop_456"])
    
    assert args.command == "reject"
    assert args.proposal_id == "prop_456"


def test_live_requires_sources():
    """Test validation fails if --live without --sources."""
    parser = create_parser()
    
    args = parser.parse_args(["run", "--live", "--top-n", "5"])
    
    with pytest.raises(CLIError, match="requires --sources"):
        validate_run_args(args)


def test_invalid_top_n():
    """Test validation fails for invalid --top-n."""
    parser = create_parser()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        args = parser.parse_args([
            "run",
            "--replay", tmpdir,
            "--top-n", "0"
        ])
        
        with pytest.raises(CLIError, match="must be at least 1"):
            validate_run_args(args)


def test_invalid_budget():
    """Test validation fails for negative budget."""
    parser = create_parser()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        args = parser.parse_args([
            "run",
            "--replay", tmpdir,
            "--budget-usd", "-1.0"
        ])
        
        with pytest.raises(CLIError, match="must be positive"):
            validate_run_args(args)


def test_missing_sources_file():
    """Test validation fails if sources file doesn't exist."""
    parser = create_parser()
    
    args = parser.parse_args([
        "run",
        "--live",
        "--sources", "/nonexistent/sources.yaml"
    ])
    
    with pytest.raises(CLIError, match="not found"):
        validate_run_args(args)


def test_missing_fixtures_dir():
    """Test validation fails if fixtures directory doesn't exist."""
    parser = create_parser()
    
    args = parser.parse_args([
        "run",
        "--replay", "/nonexistent/fixtures"
    ])
    
    with pytest.raises(CLIError, match="not found"):
        validate_run_args(args)


def test_help_does_not_crash():
    """Test --help does not crash."""
    parser = create_parser()
    
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])


def test_version_does_not_crash():
    """Test --version does not crash."""
    parser = create_parser()
    
    with pytest.raises(SystemExit):
        parser.parse_args(["--version"])
