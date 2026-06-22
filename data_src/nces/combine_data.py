# Author: Boxuan Shan + support from Claude Sonnet 4.5
#!/usr/bin/env python3
"""
Combine downloaded Excel files into master CSV files
"""

import sys
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    import pandas as pd
except ImportError:
    logger.error("pandas is not installed. Install with: pip install pandas openpyxl xlrd")
    sys.exit(1)


def combine_schools(school_type='public'):
    """Combine downloaded school files into master CSV."""

    if school_type == 'public':
        download_dir = Path('public_school_downloads')
        output_dir = Path('public_school_output')
        output_file = 'public_schools_master.csv'
        display_name = 'PUBLIC SCHOOLS'
    else:
        download_dir = Path('private_school_downloads')
        output_dir = Path('private_school_output')
        output_file = 'private_schools_master.csv'
        display_name = 'PRIVATE SCHOOLS'

    logger.info("="*70)
    logger.info(f"COMBINING {display_name}")
    logger.info("="*70)

    # Get all Excel files
    excel_files = sorted(download_dir.glob('*.xls'))
    logger.info(f"Found {len(excel_files)} Excel files")

    if not excel_files:
        logger.error(f"No files found in {download_dir}")
        return False

    # Create output directory
    output_dir.mkdir(exist_ok=True)

    # Read and combine all files
    dataframes = []
    failed_files = []

    for idx, filepath in enumerate(excel_files, 1):
        state_name = filepath.stem
        logger.info(f"[{idx}/{len(excel_files)}] Reading {state_name}...")

        try:
            # These are HTML tables saved as .xls files
            # Use read_html which returns a list of dataframes
            dfs = pd.read_html(filepath)

            # Take the first (and usually only) table
            if dfs and len(dfs) > 0:
                df = dfs[0]
            else:
                df = None

            if df is not None and len(df) > 0:
                # Add state identifier column
                df['source_file'] = state_name
                dataframes.append(df)
                logger.info(f"  ✓ Read {len(df):,} schools")
            else:
                logger.warning(f"  ✗ Empty file: {state_name}")
                failed_files.append(state_name)

        except Exception as e:
            logger.error(f"  ✗ Error reading {state_name}: {e}")
            failed_files.append(state_name)

    # Combine all dataframes
    if not dataframes:
        logger.error("No data to combine!")
        return False

    logger.info(f"\n{'='*70}")
    logger.info("COMBINING DATA")
    logger.info(f"{'='*70}")
    logger.info(f"Successfully read: {len(dataframes)}/{len(excel_files)} files")

    if failed_files:
        logger.warning(f"Failed files: {', '.join(failed_files)}")

    master_df = pd.concat(dataframes, ignore_index=True)
    output_path = output_dir / output_file

    logger.info(f"Writing to {output_path}...")
    master_df.to_csv(output_path, index=False)

    logger.info(f"\n{'='*70}")
    logger.info("SUCCESS!")
    logger.info(f"{'='*70}")
    logger.info(f"Output file: {output_path.absolute()}")
    logger.info(f"Total schools: {len(master_df):,}")
    logger.info(f"Total columns: {len(master_df.columns)}")
    logger.info(f"File size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")

    # Show column names
    logger.info(f"\nColumns included:")
    for i, col in enumerate(master_df.columns, 1):
        logger.info(f"  {i}. {col}")

    return True


def main():
    """Combine both public and private schools."""

    # Combine public schools
    logger.info("\n" + "="*70)
    logger.info("STEP 1: PUBLIC SCHOOLS")
    logger.info("="*70 + "\n")
    public_success = combine_schools('public')

    # Combine private schools
    logger.info("\n\n" + "="*70)
    logger.info("STEP 2: PRIVATE SCHOOLS")
    logger.info("="*70 + "\n")
    private_success = combine_schools('private')

    # Summary
    logger.info("\n\n" + "="*70)
    logger.info("FINAL SUMMARY")
    logger.info("="*70)
    logger.info(f"Public schools:  {'✓ SUCCESS' if public_success else '✗ FAILED'}")
    logger.info(f"Private schools: {'✓ SUCCESS' if private_success else '✗ FAILED'}")

    if public_success and private_success:
        logger.info("\n🎉 Both master CSV files created successfully!")
    elif public_success or private_success:
        logger.info("\n⚠️  One or more files failed to create")
    else:
        logger.error("\n✗ Both files failed to create")

    return 0 if (public_success and private_success) else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
