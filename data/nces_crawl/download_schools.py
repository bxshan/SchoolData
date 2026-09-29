# Author: Boxuan Shan + support from Claude Opus 4.8
#!/usr/bin/env python3
"""
NCES School Scraper (State-by-State)

Downloads Excel files from NCES school search (public or private)
for each state using Selenium, then combines into a master CSV.

Usage:
    python download_schools.py --type public
    python download_schools.py --type private
    python download_schools.py --type all      # both, then unified master CSV
"""

import os
import sys
import time
import argparse
from pathlib import Path
import logging
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# State codes (FIPS)
STATE_CODES = {
    'Alabama': '01', 'Alaska': '02', 'Arizona': '04', 'Arkansas': '05',
    'California': '06', 'Colorado': '08', 'Connecticut': '09', 'Delaware': '10',
    'District of Columbia': '11', 'Florida': '12', 'Georgia': '13', 'Hawaii': '15',
    'Idaho': '16', 'Illinois': '17', 'Indiana': '18', 'Iowa': '19',
    'Kansas': '20', 'Kentucky': '21', 'Louisiana': '22', 'Maine': '23',
    'Maryland': '24', 'Massachusetts': '25', 'Michigan': '26', 'Minnesota': '27',
    'Mississippi': '28', 'Missouri': '29', 'Montana': '30', 'Nebraska': '31',
    'Nevada': '32', 'New Hampshire': '33', 'New Jersey': '34', 'New Mexico': '35',
    'New York': '36', 'North Carolina': '37', 'North Dakota': '38', 'Ohio': '39',
    'Oklahoma': '40', 'Oregon': '41', 'Pennsylvania': '42', 'Rhode Island': '44',
    'South Carolina': '45', 'South Dakota': '46', 'Tennessee': '47', 'Texas': '48',
    'Utah': '49', 'Vermont': '50', 'Virginia': '51', 'Washington': '53',
    'West Virginia': '54', 'Wisconsin': '55', 'Wyoming': '56',
    'American Samoa': '60', 'Guam': '66', 'Northern Mariana Islands': '69',
    'Puerto Rico': '72', 'Virgin Islands': '78',
}

# Download/output dirs are resolved next to this script, so it runs from any
# working directory.
HERE = Path(__file__).resolve().parent

# NCES responses routinely take 10-15s, so allow generous timeouts and retry a
# failed state a few times before giving up on it.
# NCES can take minutes to build a state's search results. Page loads use the
# "none" strategy so driver.get() returns at once (a blocking get is capped by
# Selenium's own 120s HTTP timeout and wedges Chrome when it trips); we then
# poll up to SEARCH_TIMEOUT for the results page instead.
PAGE_LOAD_TIMEOUT = 90
SEARCH_TIMEOUT = 300
POPUP_LINK_TIMEOUT = 120
DOWNLOAD_TIMEOUT = 180
STATE_ATTEMPTS = 3

# Page assets Chrome is told not to fetch (see setup_driver).
BLOCKED_ASSETS = ["*.js", "*.js?*", "*.css", "*.css?*", "*.png", "*.gif",
                  "*.jpg", "*.svg", "*.ico", "*fonts.googleapis.com*",
                  "*fonts.gstatic.com*"]

# Returned by download_state_data when NCES reports no schools for a state —
# a legitimate empty result (e.g. private schools in a territory), not a failure.
NO_SCHOOLS = "no_schools"

# School type configurations
SCHOOL_TYPES = {
    'public': {
        'base_url': 'https://nces.ed.gov/ccd/schoolsearch/school_list.asp',
        'download_dir': 'public_school_downloads',
        'output_dir': 'output_public_schools',
        'output_file': 'public_schools_master.csv',
        'display_name': 'PUBLIC SCHOOL'
    },
    'private': {
        'base_url': 'https://nces.ed.gov/surveys/pss/privateschoolsearch/school_list.asp',
        'download_dir': 'private_school_downloads',
        'output_dir': 'output_private_schools',
        'output_file': 'private_schools_master.csv',
        'display_name': 'PRIVATE SCHOOL'
    }
}


def state_file(download_dir, state_name, state_code):
    """Canonical per-state download path, e.g. New_York_36.xls."""
    return download_dir / f"{state_name.replace(' ', '_')}_{state_code}.xls"


def setup_directories(school_type, fresh=False):
    """Create directories. Keeps finished per-state files so an interrupted run
    resumes where it stopped (fresh=True wipes them); always removes stray files
    (half-finished or un-renamed downloads) so they never reach the combine."""
    config = SCHOOL_TYPES[school_type]
    download_dir = HERE / config['download_dir']
    output_dir = HERE / config['output_dir']

    download_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    keep = set() if fresh else {state_file(download_dir, n, c).name
                                for n, c in STATE_CODES.items()}
    for f in download_dir.glob('*'):
        if f.is_file() and f.name not in keep:
            f.unlink()
    logger.info("Directories ready")

    return download_dir, output_dir


def setup_driver(download_dir):
    """Setup Chrome with download preferences."""
    chrome_options = Options()
    prefs = {
        "download.default_directory": str(download_dir.absolute()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    }
    chrome_options.add_experimental_option("prefs", prefs)
    # Don't wait for images/trackers — the NCES pages are slow (10s+ per request)
    # and only the DOM is needed to find the download link.
    chrome_options.page_load_strategy = "none"
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # Uncomment to run headless:
    # chrome_options.add_argument("--headless")

    logger.info("Starting Chrome browser...")
    logger.info("Auto-downloading correct ChromeDriver version...")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    # Every nces.ed.gov asset takes 10s+ to serve, and the page's blocking
    # scripts/stylesheets push load time past any sane timeout. None are needed:
    # GetExcelFile() and the popup's download link are inline HTML/JS.
    driver.execute_cdp_cmd("Network.enable", {})
    driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": BLOCKED_ASSETS})
    logger.info("Chrome browser started successfully")
    return driver


def construct_url(state_code, school_type):
    """Build search URL for state."""
    config = SCHOOL_TYPES[school_type]
    base_url = config['base_url']

    if school_type == 'public':
        params = [
            'Search=1', 'InstName=', 'SchoolID=', 'Address=', 'City=',
            f'State={state_code}', 'Zip=', 'Miles=', 'County=',
            'PhoneAreaCode=', 'Phone=', 'DistrictName=', 'DistrictID=',
            'SchoolType=1', 'SchoolType=2', 'SchoolType=3', 'SchoolType=4',
            'SpecificSchlTypes=all', 'IncGrade=-1', 'LoGrade=-1', 'HiGrade=-1'
        ]
    else:  # private
        params = [
            'Search=1', 'SchoolName=', 'SchoolID=', 'Address=', 'City=',
            f'State={state_code}', 'Zip=', 'Miles=', 'County=',
            'PhoneAreaCode=', 'Phone=', 'Religion=', 'Association=',
            'SchoolType=', 'Coed=', 'NumOfStudents=', 'NumOfStudentsRange=more',
            'IncGrade=-1', 'LoGrade=-1', 'HiGrade=-1'
        ]

    return f"{base_url}?{'&'.join(params)}"


def finished_downloads(paths):
    """Only a finished .xls counts. Chrome's in-progress files (.crdownload, or
    hidden ".com.google.Chrome.XXXX" on macOS) must be skipped — grabbing one
    mid-write silently truncates the state's data (this happened to Utah)."""
    return [f for f in paths
            if f.suffix.lower() == '.xls' and not f.name.startswith('.')]


def download_state_data(driver, state_name, state_code, school_type, download_dir):
    """Download Excel for one state."""
    logger.info(f"Downloading {state_name} ({state_code})...")

    try:
        # Navigate to search page
        url = construct_url(state_code, school_type)
        logger.info(f"  Navigating to URL...")
        # Clear the previous state's page first so its download link can't be
        # mistaken for this one's while the new results are still loading.
        driver.get("about:blank")
        driver.get(url)
        base_url = SCHOOL_TYPES[school_type]['base_url']

        def _results_ready(d):
            if not d.current_url.startswith(base_url):
                return False
            src = d.page_source.lower()
            return ('getexcelfile' in src or 'no schools found' in src
                    or 'no private schools' in src
                    or d.execute_script("return document.readyState") == "complete")

        WebDriverWait(driver, SEARCH_TIMEOUT, poll_frequency=2).until(_results_ready)
        time.sleep(0.5)

        # Check if page loaded
        logger.info(f"  Page loaded, looking for download link...")

        # Check for "no schools" message (mainly for private schools)
        if school_type == 'private':
            page_source = driver.page_source.lower()
            if 'no schools found' in page_source or 'no private schools' in page_source:
                logger.info(f"  No schools found for {state_name}")
                return NO_SCHOOLS

        # Find download link - it's a JavaScript link: javascript:GetExcelFile()
        download_link = None
        try:
            # Try method 1: Find by link text
            download_link = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located((By.LINK_TEXT, "Download Excel File"))
            )
            logger.info(f"  Found 'Download Excel File' link")
        except:
            pass

        if not download_link:
            try:
                # Try method 2: Find by XPath looking for the JavaScript function
                download_link = driver.find_element(By.XPATH, "//a[contains(@href, 'GetExcelFile')]")
                logger.info(f"  Found download link by XPath")
            except:
                pass

        if not download_link:
            try:
                # Try method 3: Find any link containing "Download" and "Excel"
                download_link = driver.find_element(By.XPATH, "//a[contains(text(), 'Download') and contains(text(), 'Excel')]")
                logger.info(f"  Found download link by text content")
            except:
                pass

        if not download_link:
            logger.warning(f"  ✗ No download link for {state_name}")
            return None

        # Track files before click
        before_files = set(download_dir.glob('*'))

        # Execute the JavaScript function directly instead of clicking
        logger.info(f"  Executing GetExcelFile() JavaScript function...")
        original_window = driver.current_window_handle

        try:
            # Try executing the GetExcelFile() function directly
            driver.execute_script("GetExcelFile();")
            logger.info(f"  Executed GetExcelFile() directly")
        except Exception as e:
            logger.warning(f"  Could not execute GetExcelFile() directly: {e}")
            # Fallback to clicking the link
            try:
                download_link.click()
            except:
                driver.execute_script("arguments[0].click();", download_link)

        # Handle the popup window (appears almost immediately)
        logger.info(f"  Waiting for popup window...")
        try:
            WebDriverWait(driver, 30).until(lambda d: len(d.window_handles) > 1)

            # Switch to the popup window
            for window_handle in driver.window_handles:
                if window_handle != original_window:
                    driver.switch_to.window(window_handle)
                    break

            logger.info(f"  Switched to popup, looking for 'Download Excel File' link...")

            # Wait for the Excel file to be generated and the download link to appear
            try:
                # Wait for "Download Excel File" link in popup
                # Increased timeout for large states (e.g., California with 10,000+ schools)
                excel_link = WebDriverWait(driver, POPUP_LINK_TIMEOUT).until(
                    EC.presence_of_element_located((By.LINK_TEXT, "Download Excel File"))
                )
                logger.info(f"  Found 'Download Excel File' link in popup")

                # Get the href for logging
                excel_url = excel_link.get_attribute("href")
                logger.info(f"  Excel URL: {excel_url}")

                # Click the link to download
                excel_link.click()
                logger.info(f"  Clicked 'Download Excel File' to download")
                time.sleep(0.3)  # Wait for download to start

            except Exception as e:
                logger.warning(f"  Error finding/clicking 'Download Excel File': {e}")

            # Close popup and return to main window
            driver.close()
            driver.switch_to.window(original_window)
            logger.info(f"  Closed popup, waiting for download...")

        except Exception as e:
            logger.warning(f"  No popup window: {e}")
            if driver.current_window_handle != original_window:
                driver.switch_to.window(original_window)

        # Wait for new file
        # Increased timeout for large states like California (potentially 10-15MB files)
        max_wait = int(DOWNLOAD_TIMEOUT / 0.3)
        for i in range(max_wait):
            time.sleep(0.3)
            current_files = set(download_dir.glob('*'))
            new_files = current_files - before_files

            complete_files = finished_downloads(new_files)
            if complete_files:
                # Chrome renames to the final name once the write finishes, but
                # confirm the size has settled before touching the file.
                size = complete_files[0].stat().st_size
                time.sleep(1.0)
                if complete_files[0].stat().st_size != size:
                    continue

            if complete_files:
                downloaded = complete_files[0]
                # Rename with state info
                ext = downloaded.suffix
                new_name = state_file(download_dir, state_name, state_code).with_suffix(ext)

                # Move/rename the file
                import shutil
                try:
                    if new_name.exists():
                        new_name.unlink()
                    logger.info(f"  Renaming {downloaded.name} to {new_name.name}")
                    shutil.move(downloaded, new_name)
                    logger.info(f"  ✓ Downloaded: {new_name.name}")
                except Exception as move_error:
                    logger.error(f"  Error renaming file: {move_error}")
                return new_name

        logger.warning(f"  ✗ Timeout waiting for download for {state_name}")
        return None

    except Exception as e:
        logger.error(f"  ✗ Error for {state_name}: {e}")
        if school_type == 'public':
            import traceback
            traceback.print_exc()
        return None


def process_file(filepath, school_type):
    """Read an NCES download into a clean DataFrame with real column headers.

    The downloaded .xls files are HTML tables (not real Excel), so they are
    parsed with the same stdlib HTML parser used for the unified combine.
    """
    from combine_all_schools import parse_school_file

    marker = 'NCES School ID' if school_type == 'public' else 'PSS_SCHOOL_ID'
    try:
        header, records = parse_school_file(Path(filepath), marker)
        if not records:
            logger.warning(f"  No rows parsed from {Path(filepath).name}")
            return None
        df = pd.DataFrame(records, columns=header)
        logger.info(f"  Read {len(df)} schools")
        return df

    except Exception as e:
        logger.error(f"  Error reading {Path(filepath).name}: {e}")
        return None


def restart_driver(driver, download_dir):
    """Quit a possibly-wedged Chrome and start a fresh one."""
    logger.info("  restarting Chrome...")
    try:
        driver.quit()
    except Exception:
        pass
    return setup_driver(download_dir)


def main(school_type='public', fresh=False):
    """Main function to download and process school data.

    Args:
        school_type: Either 'public' or 'private'
        fresh: re-download every state instead of reusing finished files
    """
    if school_type not in SCHOOL_TYPES:
        logger.error(f"Invalid school type: {school_type}. Must be 'public' or 'private'")
        sys.exit(1)

    config = SCHOOL_TYPES[school_type]

    logger.info("="*70)
    logger.info(f"{config['display_name']} SCRAPER - State by State")
    logger.info("="*70)
    logger.info(f"States to download: {len(STATE_CODES)}")

    download_dir, output_dir = setup_directories(school_type, fresh)

    try:
        driver = setup_driver(download_dir)
    except Exception as e:
        logger.error(f"Chrome setup failed: {e}")
        logger.error("Install ChromeDriver: brew install chromedriver")
        sys.exit(1)

    dataframes = []
    failed = []

    try:
        for idx, (state_name, state_code) in enumerate(STATE_CODES.items(), 1):
            logger.info(f"\n[{idx}/{len(STATE_CODES)}] {state_name}")

            existing = state_file(download_dir, state_name, state_code)
            if existing.exists():
                logger.info(f"  ✓ Already downloaded: {existing.name}")
                df = process_file(existing, school_type)
                if df is not None and len(df) > 0:
                    dataframes.append(df)
                continue

            downloaded = None
            for attempt in range(1, STATE_ATTEMPTS + 1):
                downloaded = download_state_data(driver, state_name, state_code, school_type, download_dir)
                if downloaded == NO_SCHOOLS:
                    downloaded = None
                    break
                if downloaded:
                    break
                # A timed-out Chrome often stays wedged; retry on a fresh one.
                driver = restart_driver(driver, download_dir)
                if attempt < STATE_ATTEMPTS:
                    logger.info(f"  retrying {state_name} ({attempt + 1}/{STATE_ATTEMPTS})...")
                    time.sleep(5 * attempt)
            else:
                failed.append(state_name)

            if downloaded:
                df = process_file(downloaded, school_type)
                if df is not None and len(df) > 0:
                    dataframes.append(df)

            time.sleep(0.2)  # Be nice to server

    finally:
        driver.quit()
        logger.info("\nBrowser closed")

    # Combine all data
    logger.info(f"\n{'='*70}")
    logger.info("COMBINING DATA")
    logger.info(f"{'='*70}")
    logger.info(f"States downloaded: {len(dataframes)}/{len(STATE_CODES)}")
    if failed:
        logger.warning(f"States FAILED after {STATE_ATTEMPTS} attempts: {', '.join(failed)}")

    if dataframes:
        master_df = pd.concat(dataframes, ignore_index=True)
        output_path = output_dir / config['output_file']
        if failed:
            # Never replace a complete master with a partial one.
            output_path = output_path.with_suffix('.partial.csv')
            logger.warning(f"Incomplete download — writing {output_path.name} "
                           f"instead of overwriting {config['output_file']}")
        master_df.to_csv(output_path, index=False)

        logger.info(f"\n{'='*70}")
        logger.info("SUCCESS!")
        logger.info(f"{'='*70}")
        logger.info(f"File: {output_path.absolute()}")
        logger.info(f"Total schools: {len(master_df):,}")
        logger.info(f"Columns: {len(master_df.columns)}")
    else:
        logger.error("No data downloaded")
    return bool(dataframes) and not failed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Download NCES school data by state')
    parser.add_argument(
        '--type',
        choices=['public', 'private', 'all'],
        default='public',
        help="Type of schools to download: 'public', 'private', or "
             "'all' (both, then build the unified all-K-12 master CSV)"
    )
    parser.add_argument(
        '--fresh', action='store_true',
        help="re-download every state (default: reuse per-state files already "
             "in the download dir, so an interrupted run resumes)"
    )

    args = parser.parse_args()

    try:
        if args.type == 'all':
            ok_public = main(school_type='public', fresh=args.fresh)
            ok_private = main(school_type='private', fresh=args.fresh)
            if ok_public and ok_private:
                from combine_all_schools import build_unified
                build_unified()
            else:
                logger.error("Skipping unified master: a sector download was "
                             "incomplete (see FAILED states above)")
                sys.exit(1)
        else:
            main(school_type=args.type, fresh=args.fresh)
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
