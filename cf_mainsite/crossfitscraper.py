#!/usr/bin/env python3
"""
CrossFit WOD TRMNL Plugin Server - Clean Version
Scrapes daily workout from crossfit.com and sends to TRMNL device
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import datetime
import logging
import os
import csv
from pathlib import Path
from dotenv import load_dotenv

load_dotenv() 

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WorkoutData:
    """Data structure for CrossFit workout information"""
    def __init__(self, title, description, movements, scaling, stimulus, date, date_code, 
                 is_named_workout=False, is_hero_workout=False, is_rest_day=False, scraped_at=""):
        self.title = title
        self.description = description
        self.movements = movements
        self.scaling = scaling
        self.stimulus = stimulus
        self.date = date
        self.date_code = date_code
        self.is_named_workout = is_named_workout
        self.is_hero_workout = is_hero_workout
        self.is_rest_day = is_rest_day
        self.scraped_at = scraped_at
    
    def to_csv_row(self):
        """Convert to CSV-friendly format"""
        return {
            'date_code': self.date_code,
            'date': self.date,
            'title': self.title,
            'is_named_workout': str(self.is_named_workout),
            'is_hero_workout': str(self.is_hero_workout),
            'is_rest_day': str(self.is_rest_day),
            'description': self.description.replace('\n', ' | ').replace('\r', ''),
            'movements': ' | '.join(self.movements) if self.movements else '',
            'scaling': self.scaling.replace('\n', ' | ').replace('\r', ''),
            'stimulus': self.stimulus.replace('\n', ' | ').replace('\r', ''),
            'scraped_at': self.scraped_at,
            'url': f"https://www.crossfit.com/{self.date_code}"
        }

class CrossFitWODScraper:
    """Scrapes workout data from crossfit.com"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_workout_url(self, date=None):
        """Generate the CrossFit workout URL for a specific date"""
        if date is None:
            date = datetime.date.today()
        
        date_str = date.strftime("%y%m%d")
        return f"https://www.crossfit.com/{date_str}"
    
    def fetch_workout_page(self, date=None):
        """Fetch the workout page HTML and return HTML + date string"""
        workout_url = self.get_workout_url(date)
        date_str = date.strftime("%y%m%d") if date else datetime.date.today().strftime("%y%m%d")
        
        try:
            logger.info(f"Fetching workout from: {workout_url}")
            response = self.session.get(workout_url)
            response.raise_for_status()
            return response.text, date_str
        except requests.RequestException as e:
            logger.error(f"Failed to fetch workout page from {workout_url}: {e}")
            raise
    
    def parse_workout_data(self, html, date_str):
        """Parse the workout data from HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Get formatted date for display
        date_obj = datetime.datetime.strptime(date_str, "%y%m%d").date()
        formatted_date = date_obj.strftime("%B %d, %Y")
        
        # Extract workout content
        workout_content = self._extract_workout_content(soup, date_str)
        
        return WorkoutData(
            title=workout_content.get('title', date_str),
            description=workout_content.get('description', ''),
            movements=workout_content.get('movements', []),
            scaling=workout_content.get('scaling', ''),
            stimulus=workout_content.get('stimulus', ''),
            date=formatted_date,
            date_code=date_str,
            is_named_workout=workout_content.get('is_named_workout', False),
            is_hero_workout=workout_content.get('is_hero_workout', False),
            is_rest_day=workout_content.get('is_rest_day', False),
            scraped_at=datetime.datetime.now().isoformat()
        )
    
    def _extract_workout_content(self, soup, date_str):
        """Extract workout content from the parsed HTML"""
        content = {
            'title': date_str,
            'description': '',
            'movements': [],
            'scaling': '',
            'stimulus': '',
            'is_named_workout': False,
            'is_hero_workout': False,
            'is_rest_day': False
        }
        
        # Remove comment sections to avoid parsing user comments
        for comment_section in soup.find_all(['div', 'section'], class_=re.compile('comment', re.I)):
            comment_section.decompose()
        
        # Look for elements with "Comments on" text and remove everything after
        for element in soup.find_all(string=re.compile(r'Comments on \d+', re.I)):
            parent = element.find_parent()
            if parent:
                # Remove this element and all following siblings
                for sibling in parent.find_next_siblings():
                    sibling.decompose()
                parent.decompose()
        
        page_text = soup.get_text().lower()
        
        # Look for Rest Day indicator first
        if 'rest day' in page_text:
            content['is_rest_day'] = True
            content['description'] = "Rest Day - Recovery and mobility work recommended"
            return content
        
        # Look for bold text that might contain the title (like **2025 CrossFit Games Event 1**)
        potential_titles = []
        
        # Check for text in strong/b tags
        for bold in soup.find_all(['strong', 'b']):
            text = bold.get_text().strip()
            if text and len(text) > 5 and len(text) <= 50:
                # Skip promotional banners and watch now messages
                skip_phrases = ['watch now', 'are live', 'shop', 'buy', 'sale', 'click here', 'subscribe']
                if any(phrase in text.lower() for phrase in skip_phrases):
                    continue
                
                # Prioritize titles with "Event" followed by a number
                if re.search(r'event\s+\d+', text.lower()):
                    potential_titles.insert(0, text)  # Put at beginning of list
                # Check if it looks like a title (contains Games, Event, Hero name, etc.)
                elif any(keyword in text.lower() for keyword in ['games', 'hero', 'benchmark']):
                    potential_titles.append(text)
                elif text.isupper() or (text[0].isupper() and not any(c.islower() for c in text[1:])):
                    potential_titles.append(text)
        
        # Also check headings
        for heading in soup.find_all(['h1', 'h2', 'h3']):
            text = heading.get_text().strip()
            
            skip_patterns = [
                'workout of the day', 'wod', 'scaling', 'stimulus', 'strategy',
                'coaching', 'resources', 'post', 'compare', 'intermediate option', 'beginner option',
                'comments'
            ]
            
            if text and len(text) <= 50 and not any(skip in text.lower() for skip in skip_patterns):
                if (text.isupper() or text.istitle() or 
                    re.match(r'^[A-Z][a-z]+$', text) or 
                    'games' in text.lower() or
                    'event' in text.lower()):
                    potential_titles.append(text)
        
        # Use the first good title found
        if potential_titles:
            content['title'] = potential_titles[0]
            content['is_named_workout'] = True
            
            # Check if it's a Games workout
            if 'games' in potential_titles[0].lower():
                content['is_named_workout'] = True
        
        # Extract main workout description
        workout_lines = []
        found_workout = False
        workout_title_candidate = None
        
        # Look for "For time:" or similar workout indicators
        all_text = soup.get_text()
        lines = all_text.split('\n')
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or 'commented on:' in line.lower():
                continue
            
            # Check if this line might be a workout title (appears right before workout)
            if i > 0 and i < len(lines) - 1:
                next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                if any(indicator in next_line.lower() for indicator in ['for time:', 'amrap', 'emom', 'rounds for time:', 'complete:']):
                    # This line might be the workout title
                    if 'event' in line.lower() or 'games' in line.lower():
                        workout_title_candidate = line.replace('**', '').strip()
                
            # Look for workout start indicators
            if any(indicator in line.lower() for indicator in ['for time:', 'amrap', 'emom', 'rounds for time:', 'complete:']):
                found_workout = True
            
            # If we found the workout, collect lines until we hit a section marker
            if found_workout:
                section_markers = ['stimulus', 'scaling', 'intermediate option', 'beginner option', 
                                 'coaching', 'resources', 'comments', 'post time']
                
                if any(marker in line.lower() for marker in section_markers):
                    break
                    
                if line and not line.startswith('**'):  # Skip markdown formatting
                    workout_lines.append(line)
        
        if workout_lines:
            content['description'] = '\n'.join(workout_lines[:10])  # Limit to first 10 lines
        
        # Extract movements from the description
        movements = []
        movement_patterns = [
            r'(\d+(?:,\d+)?(?:-meter|-mile)?)\s+([a-zA-Z\-\s]+)',
            r'([A-Z][a-zA-Z\-\s]+?)(?=\n|♀|♂|\d|$)',
        ]
        
        for line in workout_lines:
            # Look for distance/rep + movement patterns
            matches = re.findall(r'(\d+(?:,\d+)?(?:-meter|-mile)?)\s+([a-zA-Z\-\s]+?)(?=\n|,|$)', line)
            for match in matches:
                if len(match) == 2:
                    movement = f"{match[0]} {match[1].strip()}"
                    if 3 < len(movement) < 50:
                        movements.append(movement)
        
        content['movements'] = list(dict.fromkeys(movements))[:8]  # Remove duplicates, limit to 8
        
        # Extract scaling information more carefully
        scaling_parts = []
        
        # Method 1: Look for specific scaling section
        scaling_section_found = False
        for i, line in enumerate(lines):
            if 'scaling:' in line.lower():
                scaling_section_found = True
                # Collect the next few lines until we hit another section
                for j in range(i+1, min(i+10, len(lines))):
                    next_line = lines[j].strip()
                    if not next_line:
                        continue
                    if any(marker in next_line.lower() for marker in ['intermediate option:', 'beginner option:', 
                                                                       'coaching', 'resources', 'stimulus']):
                        break
                    if next_line and not next_line.startswith('**'):
                        scaling_parts.append(next_line)
                break
        
        # Method 2: Look for Intermediate and Beginner options
        for option_type in ['intermediate option:', 'beginner option:']:
            for i, line in enumerate(lines):
                if option_type in line.lower():
                    option_text = [line]
                    
                    # Collect the workout description for this option
                    for j in range(i+1, min(i+10, len(lines))):
                        next_line = lines[j].strip()
                        if not next_line:
                            continue
                        # Stop at next section or option
                        if any(marker in next_line.lower() for marker in ['option:', 'coaching', 'resources', 'stimulus', 'comments']):
                            break
                        if next_line and not next_line.startswith('**'):
                            option_text.append(next_line)
                    
                    if len(option_text) > 1:
                        scaling_parts.append('\n'.join(option_text))
        
        if scaling_parts:
            content['scaling'] = '\n\n'.join(scaling_parts)
        
        # Extract stimulus/strategy information
        stimulus_section_found = False
        stimulus_lines = []
        
        for i, line in enumerate(lines):
            if 'stimulus and strategy:' in line.lower() or 'stimulus:' in line.lower():
                stimulus_section_found = True
                # Collect the next few lines
                for j in range(i+1, min(i+10, len(lines))):
                    next_line = lines[j].strip()
                    if not next_line:
                        continue
                    if any(marker in next_line.lower() for marker in ['scaling:', 'intermediate option:', 
                                                                       'beginner option:', 'coaching', 'resources']):
                        break
                    if next_line and not next_line.startswith('**'):
                        stimulus_lines.append(next_line)
                break
        
        if stimulus_lines:
            content['stimulus'] = ' '.join(stimulus_lines)
        
        # Hero workout detection (keep the existing logic but be more strict)
        hero_indicators = ['lt.', 'lieutenant', 'sgt.', 'sergeant', 'cpl.', 'corporal', 
                          'pfc.', 'private', 'captain', 'major', 'colonel']
        hero_phrases = ['fallen', 'killed in action', 'kia', 'memorial', 'died', 'gave his life', 'gave her life']
        
        has_military_rank = any(indicator in page_text for indicator in hero_indicators)
        has_memorial_language = any(phrase in page_text for phrase in hero_phrases)
        is_reference_only = ('reminiscent of a hero workout' in page_text or 
                           'similar to' in page_text or 
                           'like the hero workout' in page_text)
        
        if has_military_rank and has_memorial_language and not is_reference_only:
            content['is_hero_workout'] = True
            content['is_named_workout'] = True
        
        return content

class CSVLogger:
    """Logs workout data to CSV file"""
    
    def __init__(self, csv_file_path="crossfit_workouts.csv"):
        self.csv_file_path = Path(csv_file_path)
        self.fieldnames = [
            'date_code', 'date', 'title', 'is_named_workout', 'is_hero_workout', 'is_rest_day',
            'description', 'movements', 'scaling', 'stimulus', 'scraped_at', 'url'
        ]
        self._ensure_csv_exists()
    
    def _ensure_csv_exists(self):
        """Create CSV file with headers if it doesn't exist"""
        if not self.csv_file_path.exists():
            with open(self.csv_file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=self.fieldnames)
                writer.writeheader()
            logger.info(f"Created new CSV file: {self.csv_file_path}")
    
    def workout_exists(self, date_code):
        """Check if a workout for this date already exists in CSV"""
        if not self.csv_file_path.exists():
            return False
        
        try:
            with open(self.csv_file_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if row.get('date_code') == date_code:
                        return True
        except Exception as e:
            logger.warning(f"Error reading CSV file: {e}")
        
        return False
    
    def log_workout(self, workout, overwrite=False):
        """Log workout data to CSV file"""
        try:
            if not overwrite and self.workout_exists(workout.date_code):
                logger.info(f"Workout {workout.date_code} already exists in CSV. Skipping.")
                return True
            
            if overwrite and self.workout_exists(workout.date_code):
                self._update_existing_workout(workout)
            else:
                with open(self.csv_file_path, 'a', newline='', encoding='utf-8') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=self.fieldnames)
                    writer.writerow(workout.to_csv_row())
            
            logger.info(f"Logged workout {workout.date_code} ({workout.title}) to CSV")
            return True
            
        except Exception as e:
            logger.error(f"Failed to log workout to CSV: {e}")
            return False
    
    def _update_existing_workout(self, workout):
        """Update an existing workout in the CSV file"""
        rows = []
        with open(self.csv_file_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row.get('date_code') == workout.date_code:
                    rows.append(workout.to_csv_row())
                else:
                    rows.append(row)
        
        with open(self.csv_file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    
    def get_workout_stats(self):
        """Get basic statistics about logged workouts"""
        if not self.csv_file_path.exists():
            return {}
        
        stats = {
            'total_workouts': 0,
            'named_workouts': 0,
            'hero_workouts': 0,
            'rest_days': 0,
            'most_recent': None
        }
        
        try:
            with open(self.csv_file_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                
                for row in reader:
                    stats['total_workouts'] += 1
                    
                    if row.get('is_named_workout') == 'True':
                        stats['named_workouts'] += 1
                    
                    if row.get('is_hero_workout') == 'True':
                        stats['hero_workouts'] += 1
                    
                    if row.get('is_rest_day') == 'True':
                        stats['rest_days'] += 1
                    
                    stats['most_recent'] = row.get('title')
        
        except Exception as e:
            logger.warning(f"Error calculating stats: {e}")
        
        return stats

class TRMNLWebhookSender:
    """Sends workout data to TRMNL via webhook"""
    
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
    
    def send_workout_data(self, workout):
        """Send workout data to TRMNL webhook"""
        try:
            payload = {
                "merge_variables": {
                    "workout_title": workout.title,
                    "workout_date": workout.date,
                    "workout_description": workout.description,
                    "workout_movements": workout.movements,
                    "workout_scaling": workout.scaling,
                    "workout_stimulus": workout.stimulus,
                    "is_named_workout": workout.is_named_workout,
                    "is_hero_workout": workout.is_hero_workout,
                    "is_rest_day": workout.is_rest_day,
                    "last_updated": datetime.datetime.now().strftime("%H:%M"),
                    "date_code": workout.date_code
                }
            }
            
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            logger.info("Successfully sent workout data to TRMNL")
            return True
            
        except requests.RequestException as e:
            logger.error(f"Failed to send data to TRMNL: {e}")
            return False

def main():
    """Main function to scrape workout and send to TRMNL"""
    webhook_url = os.getenv('TRMNL_WEBHOOK_URL')
    if not webhook_url:
        logger.error("TRMNL_WEBHOOK_URL environment variable not set")
        return
    
    csv_file = os.getenv('CROSSFIT_CSV_FILE', 'crossfit_workouts.csv')
    
    date_env = os.getenv('WORKOUT_DATE')
    workout_date = None
    
    if date_env:
        try:
            workout_date = datetime.datetime.strptime(date_env, "%Y-%m-%d").date()
            logger.info(f"Using specific date: {workout_date}")
        except ValueError:
            logger.warning(f"Invalid date format in WORKOUT_DATE: {date_env}. Using today's date.")
    
    overwrite_csv = os.getenv('OVERWRITE_CSV', 'false').lower() == 'true'
    
    try:
        csv_logger = CSVLogger(csv_file)
        
        scraper = CrossFitWODScraper()
        html, date_str = scraper.fetch_workout_page(workout_date)
        workout = scraper.parse_workout_data(html, date_str)
        
        csv_success = csv_logger.log_workout(workout, overwrite=overwrite_csv)
        
        sender = TRMNLWebhookSender(webhook_url)
        trmnl_success = sender.send_workout_data(workout)
        
        stats = csv_logger.get_workout_stats()
        if stats:
            logger.info(f"CSV Stats - Total: {stats['total_workouts']}, "
                       f"Named: {stats['named_workouts']}, "
                       f"Hero: {stats['hero_workouts']}, "
                       f"Rest Days: {stats['rest_days']}")
        
        if csv_success and trmnl_success:
            logger.info(f"Successfully processed workout: {workout.title} ({date_str})")
        elif csv_success:
            logger.warning("CSV logged successfully but TRMNL update failed")
        elif trmnl_success:
            logger.warning("TRMNL updated successfully but CSV logging failed")
        else:
            logger.error("Both CSV logging and TRMNL update failed")
            
    except Exception as e:
        logger.error(f"Error processing workout: {e}")

if __name__ == "__main__":
    main()