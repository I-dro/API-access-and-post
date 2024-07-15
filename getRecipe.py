import requests
import firebase_admin
from firebase_admin import credentials, firestore
import json
import os
import re

# Environment variable names for sensitive data
UID_CACHE_FILE_ENV = 'UID_CACHE_FILE_PATH'
FIREBASE_CRED_ENV = 'FIREBASE_CREDENTIALS_PATH'
SPOONACULAR_API_KEY_ENV = 'SPOONACULAR_API_KEY'

# Path to the JSON file for local UID cache
UID_CACHE_FILE = os.getenv(UID_CACHE_FILE_ENV)

# Initialize Firebase Admin SDK
firebase_credentials_path = os.getenv(FIREBASE_CRED_ENV)
cred = credentials.Certificate(firebase_credentials_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

def load_uid_cache():
    """Load UID cache from a local JSON file."""
    if os.path.exists(UID_CACHE_FILE):
        try:
            with open(UID_CACHE_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            # If the file is empty or not in valid JSON format, return an empty dictionary
            return {}
    return {}

def save_uid_cache(cache):
    """Save UID cache to a local JSON file."""
    with open(UID_CACHE_FILE, 'w') as f:
        json.dump(cache, f)

def initialize_uid_cache():
    """Initialize the UID cache from the local file or Firestore if the local cache is empty."""
    global uid_cache
    uid_cache = load_uid_cache()
    if not uid_cache:
        # Fetch all existing UIDs from Firestore if the local cache is empty
        recipes_ref = db.collection('recipes')
        docs = recipes_ref.stream()
        for doc in docs:
            uid_cache[doc.id] = True
        save_uid_cache(uid_cache)

def fetch_recipes():
    """Fetch random recipes from the Spoonacular API."""
    api_key = os.getenv(SPOONACULAR_API_KEY_ENV)
    url = f"https://api.spoonacular.com/recipes/random?apiKey={api_key}&number=10"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data['recipes']
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching recipes: {e}")
        return []

def recipe_exists(recipe_id):
    """Check if a recipe with the given ID already exists in the local UID cache."""
    return uid_cache.get(str(recipe_id), False)

def extract_equipment(analyzed_instructions):
    """Extract a list of equipment from the analyzed instructions."""
    equipment_set = set()
    for instruction in analyzed_instructions:
        for step in instruction.get('steps', []):
            for equipment in step.get('equipment', []):
                equipment_set.add(equipment['name'])
    return list(equipment_set)

def extract_and_categorize(text):
    """Extract and categorize nutritional information from the text."""
    # Extracting the content inside <b></b> tags
    b_tags = re.findall(r'<b>(.*?)</b>', text)
    
    # Predefined categories and their patterns
    categories = {
        'Cost per serving': r'\d+ cents per serving',
        'Protein': r'\d+g of protein',
        'Fat': r'\d+g of fat',
        'Calories': r'\d+ calories',
    }
    
    categorized_data = {}

    for tag in b_tags:
        for category, pattern in categories.items():
            if re.search(pattern, tag):
                # Cleaning the data to make it more readable
                clean_data = re.sub(r'[^0-9a-zA-Z\s]', '', tag)
                categorized_data[category] = clean_data
                break

    return categorized_data

def store_recipes(recipes):
    """Store the fetched recipes in Firestore and update the local UID cache."""
    global uid_cache
    for recipe in recipes:
        try:
            recipe_id = recipe['id']
            if not recipe_exists(recipe_id):
                ingredients_map = {
                    ingredient['name']: f"{ingredient['amount']} {ingredient['unit']}"
                    for ingredient in recipe['extendedIngredients']
                }

                equipment_list = extract_equipment(recipe.get('analyzedInstructions', []))

                # Extract and categorize nutritional information
                summary = recipe.get('summary', '')
                nutritional_info = extract_and_categorize(summary)
                
                if 'Calories' in nutritional_info:
                    calories_str = str(nutritional_info['Calories'])  # Get the calories as string
                    # Remove non-numeric characters
                    calories_clean = re.sub(r'\D', '', calories_str)
                    # Convert to integer
                    calories_int = int(calories_clean)

                    # Update nutritional info with cleaned and converted calories
                    caloriesInt = calories_int
                else:
                    caloriesInt = 0

                doc_ref = db.collection('recipes').document(str(recipe_id))
                doc_ref.set({
                    'title': recipe['title'],
                    'ingredients': ingredients_map,
                    'instructions': recipe['instructions'] if recipe['instructions'] else 'No instructions provided',
                    'vegetarian': recipe.get('vegetarian', False),
                    'vegan': recipe.get('vegan', False),
                    'glutenFree': recipe.get('glutenFree', False),
                    'dairyFree': recipe.get('dairyFree', False),
                    'healthiness': recipe.get('healthScore', 0),
                    'calories': caloriesInt,
                    'time': recipe.get('readyInMinutes', 0),
                    'servings': recipe.get('servings', 0),
                    'image': recipe.get('image', ''),
                    'source': recipe.get('sourceUrl', ''),
                    'equipment': equipment_list,
                    'summary': recipe['summary'],
                    'nutritional': nutritional_info,
                    'cost': nutritional_info.get('Cost per serving', 0)
                })
                print(f"Stored recipe: {recipe['title']}")
                # Update the local cache with the new UID and save to file
                uid_cache[str(recipe_id)] = True
                save_uid_cache(uid_cache)
            else:
                print(f"Duplicate recipe found: {recipe['title']}")
        except Exception as e:
            print(f"An error occurred while storing recipe '{recipe['title']}': {e}")

if __name__ == '__main__':
    initialize_uid_cache()
    recipes = fetch_recipes()
    if recipes:
        store_recipes(recipes)
        print("Recipes have been successfully stored in Firebase Firestore")
    else:
        print("No recipes to store")
