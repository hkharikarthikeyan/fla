from flask import Flask, request, jsonify
from flask_cors import CORS
from bs4 import BeautifulSoup
import requests
import time
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from pymongo import MongoClient
from bson import son
import re
from datetime import datetime
# Initialize Flask App
app = Flask(__name__)
CORS(app)

# MongoDB Connection
MONGO_URI = "mongodb+srv://harik:hari919597@cluster1.vpugu.mongodb.net/?retryWrites=true&w=majority&appName=Cluster1"
client = MongoClient(MONGO_URI)
db = client["myDatabase"]
collection = db["products"]

# Selenium WebDriver Setup
chrome_options = Options()
chrome_options.add_argument("--headless")  # Remove this line to see browser window
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

webdriver_service = Service(r"C:\Users\Harikarthikeyan\Downloads\ecommerce-price-comparison\chromedriver.exe")

# Function to extract Amazon product details
def get_amazon_product_details(soup):
    try:
        title = soup.find("span", attrs={"id": "productTitle"}).text.strip()
    except AttributeError:
        title = "N/A"

    try:
        price = soup.find("span", attrs={'class': 'a-price-whole'}).text.strip()
        fraction = soup.find("span", attrs={'class': 'a-price-fraction'}).text.strip()
        price = price + fraction
    except AttributeError:
        price = "Not Available"

    try:
        available = soup.find("div", attrs={'id': 'availability'}).find("span").text.strip()
    except AttributeError:
        available = "Not Available"

    try:
        image = soup.find("img", attrs={"id": "landingImage"})["src"]
    except (AttributeError, TypeError):
        image = "N/A"

    return {
        "name": title,
        "price": price,
        "availability": available,
        "image": image,
        "source": "Amazon"
    }

# Function to scrape Amazon product page
def scrape_amazon_product(link):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        webpage = requests.get(link, headers=headers)
        time.sleep(1)
        soup = BeautifulSoup(webpage.content, "html.parser")
        return get_amazon_product_details(soup)
    except Exception as e:
        print(f"Error scraping {link}: {e}")
        return None

# Function to scrape Amazon product links
def scrape_amazon(search_url):
    driver = webdriver.Chrome(service=webdriver_service, options=chrome_options)
    driver.get(search_url)

    product_links = set()
    while True:
        soup = BeautifulSoup(driver.page_source, "html.parser")
        links = soup.find_all("a", attrs={'class': 'a-link-normal s-no-outline'})
        product_links.update(["https://www.amazon.in" + link.get('href') for link in links])

        try:
            next_button = driver.find_element(By.CSS_SELECTOR, "li.a-last a")
            next_button.click()
            time.sleep(2)
        except:
            break

    driver.quit()
    print(f"Found {len(product_links)} Amazon product links.")

    products = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        scraped_products = list(filter(None, executor.map(scrape_amazon_product, product_links)))

    return scraped_products

# Function to extract eBay product details
def get_ebay_product_details(item):
    try:
        title = item.find("div", class_="s-item__title").text.strip() if item.find("div", class_="s-item__title") else "N/A"
        price = item.find("span", class_="s-item__price").text.strip() if item.find("span", class_="s-item__price") else "N/A"
        shipping = item.find("span", class_="s-item__shipping").text.strip() if item.find("span", class_="s-item__shipping") else "N/A"
        
        # Extract image URL
        image_url = "N/A"
        image_container = item.find("div", class_="s-item__image")
        if image_container:
            image_tag = image_container.find("img")
            if image_tag:
                image_url = image_tag.get("src") or image_tag.get("data-src", "N/A")

        return {"name": title, "price": price, "image": image_url, "shipping_details": shipping, "source": "eBay"}
    except Exception as e:
        print(f"❌ Error extracting eBay product details: {e}")
        return None

# Function to scrape eBay search results
def scrape_ebay(search_query):
    base_url = f"https://www.ebay.com/sch/i.html?_nkw={search_query}"
    try:
        driver = webdriver.Chrome(service=webdriver_service, options=chrome_options)
        driver.get(base_url)
        time.sleep(3)  # Allow time for page to load

        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # DEBUG: Print page source if eBay doesn't work
        print("🔍 eBay Page Source Loaded!")
        
        # Find all product listings
        items = soup.find_all("div", class_="s-item__wrapper")

        if not items:
            print("⚠️ No eBay products found. Check the website structure!")

        products = [get_ebay_product_details(item) for item in items if item]
        return products[:25]  # Limit to 25 products
    finally:
        driver.quit()  # Ensure WebDriver is closed

# Function to convert ObjectId to string for JSON response
def serialize_product(product):
    product["_id"] = str(product["_id"])
    return product

# Flask Routes
@app.route('/')
def home():
    return jsonify({"message": "Flask API is running!"})

@app.route('/api/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    product_name = data.get("product_name", "").strip()
    if not product_name:
        return jsonify({"error": "Product name is required"}), 400

    # Scrape Amazon
    amazon_search_url = f"https://www.amazon.in/s?k={product_name.replace(' ', '+')}"
    amazon_products = scrape_amazon(amazon_search_url)

    # Scrape eBay
    ebay_products = scrape_ebay(product_name)

    # Combine results
    all_products = amazon_products + ebay_products

    if all_products:
        # Store data in MongoDB
        collection.insert_many(all_products)

        # Retrieve only the searched product from MongoDB
        regex_pattern = re.compile(product_name, re.IGNORECASE)
        filtered_products = list(collection.find({"name": regex_pattern}).limit(10))

        json_products = [serialize_product(p) for p in filtered_products]

        return jsonify({"message": "Scraping successful!", "data": json_products})
    else:
        return jsonify({"message": "No products found."}), 404

@app.route('/api/products', methods=['GET'])
def get_products():
    product_name = request.args.get("product_name", "").strip()
    
    if product_name:
        regex_pattern = re.compile(product_name, re.IGNORECASE)
        products = list(collection.find({"name": regex_pattern}).limit(10))
    else:
        products = list(collection.find().limit(10))

    return jsonify([serialize_product(p) for p in products])
# Helper function to convert ObjectId to string
def serialize_product(product):
    product["_id"] = str(product["_id"])
    return product

# ✅ **New Route: Get Price History for a Product**
@app.route('/api/price-history', methods=['GET'])
def get_price_history():
    product_title = request.args.get("title", "").strip()
    
    if not product_title:
        return jsonify({"error": "Product title is required"}), 400
    
    # Search for the product by title (case-insensitive)
    regex_pattern = re.compile(f"^{re.escape(product_title)}$", re.IGNORECASE)
    product = collection.find_one({"name": regex_pattern})
    
    if not product or "price_history" not in product:
        return jsonify({"message": "No price history available.", "priceHistory": []}), 404

    return jsonify({
        "message": "Price history retrieved successfully",
        "priceHistory": product["price_history"]
    })

# ✅ **Modify Scraping to Save Price History**
def save_price_history(product_name, price, platform):
    existing_product = collection.find_one({"name": product_name, "source": platform})

    # Prepare new price history entry
    price_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "price": float(price.replace(",", "").replace("₹", "").strip()) if price.replace(",", "").replace("₹", "").strip().replace(".", "").isdigit() else None,
        "platform": platform
    }

    if existing_product:
        # Update existing product with new price history
        collection.update_one(
            {"_id": existing_product["_id"]},
            {"$push": {"price_history": price_entry}}
        )
    else:
        # Create a new product entry with price history
        collection.insert_one({
            "name": product_name,
            "price_history": [price_entry],
            "source": platform
        })

# Run Flask App
if __name__ == '__main__':
    app.run(debug=True, port=5000)
