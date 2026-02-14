#!/usr/bin/env python3
"""
Simple runner script for isrc101-agent.

This script provides an alternative way to start the application
without needing to install the package first.
"""

import sys
import os
from pathlib import Path

def main():
    # Add the current directory to Python path
    current_dir = Path(__file__).parent
    sys.path.insert(0, str(current_dir))
    
    # Check if the main module exists
    main_py = current_dir / "main.py"
    if not main_py.exists():
        print("Error: main.py not found!")
        print("Please run this script from the project root directory.")
        sys.exit(1)
    
    # Import and run the main function
    try:
        from main import main as app_main
        app_main()
    except ImportError as e:
        print(f"Import error: {e}")
        print("\nTrying to run the package directly...")
        try:
            # Try to run the package directly
            from isrc101_agent.main import cli
            cli()
        except ImportError:
            print("\nPlease install the package first:")
            print("  pip install -e .")
            print("\nOr run the CLI directly:")
            print("  python -m isrc101_agent.main")
            sys.exit(1)

if __name__ == "__main__":
    main()