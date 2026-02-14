#!/usr/bin/env python3
"""
isrc101-agent - AI coding assistant for your terminal.

This is the main entry point for the application.
It provides a simple way to start the interactive session.
"""

import sys
import os
from pathlib import Path

# Add the current directory to Python path to ensure imports work
sys.path.insert(0, str(Path(__file__).parent))

def main():
    """
    Main entry point for the application.
    
    This function:
    1. Sets up the environment
    2. Imports the CLI application
    3. Runs the main command
    """
    try:
        # Import the CLI application from the package
        from isrc101_agent.main import cli
        
        # Run the CLI application
        cli()
    except ImportError as e:
        print(f"Error: Failed to import required modules: {e}")
        print("Please make sure you have installed the package with:")
        print("  pip install -e .")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        if os.environ.get("ISRC101_VERBOSE"):
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()