# Login-once adapters. Nightly runs reuse the Unraid Chromium profile.
# Stop and notify on login/CAPTCHA. No stealth, proxies, or solvers.

SUPPLIERS: list[dict] = [
    {
        "slug": "chefs-warehouse",
        "label": "Chef's Warehouse",
        "needs_login": True,
        "login_url": "https://www.chefswarehouse.com/login/",
        "home_url": "https://www.chefswarehouse.com/",
        "search_url": "https://www.chefswarehouse.com/search?q={query}",
    },
    {
        "slug": "gordon",
        "label": "Gordon Food Service",
        "needs_login": True,
        "login_url": "https://order.gfs.com/",
        "home_url": "https://order.gfs.com/",
        "search_url": "https://order.gfs.com/search?k={query}",
    },
    {
        "slug": "sams-club",
        "label": "Sam's Club",
        "needs_login": True,
        "login_url": "https://www.samsclub.com/login",
        "home_url": "https://www.samsclub.com/",
        "search_url": "https://www.samsclub.com/s/{query}",
    },
    {
        "slug": "costco",
        "label": "Costco",
        "needs_login": True,
        "login_url": "https://www.costco.com/LogonForm",
        "home_url": "https://www.costco.com/",
        "search_url": "https://www.costco.com/s?keyword={query}",
    },
    {
        "slug": "restaurant-depot",
        "label": "Restaurant Depot",
        "needs_login": True,
        "login_url": "https://www.restaurantdepot.com/",
        "home_url": "https://www.restaurantdepot.com/",
        "search_url": "https://www.restaurantdepot.com/search?q={query}",
    },
    {
        "slug": "webstaurantstore",
        "label": "WebstaurantStore",
        "needs_login": False,
        "login_url": "https://www.webstaurantstore.com/",
        "home_url": "https://www.webstaurantstore.com/",
        "search_url": "https://www.webstaurantstore.com/search/{slug}.html",
    },
    {
        "slug": "publix",
        "label": "Publix",
        "needs_login": False,
        "login_url": "https://www.publix.com/",
        "home_url": "https://www.publix.com/",
        "search_url": "https://www.publix.com/shop/search?searchTerm={query}",
    },
    {
        "slug": "walmart",
        "label": "Walmart",
        "needs_login": False,
        "login_url": "https://www.walmart.com/",
        "home_url": "https://www.walmart.com/",
        "search_url": "https://www.walmart.com/search?q={query}",
    },
    {
        "slug": "target",
        "label": "Target",
        "needs_login": False,
        "login_url": "https://www.target.com/",
        "home_url": "https://www.target.com/",
        "search_url": "https://www.target.com/s?searchTerm={query}",
    },
    {
        "slug": "aldi",
        "label": "Aldi",
        "needs_login": False,
        "login_url": "https://www.aldi.us/",
        "home_url": "https://www.aldi.us/",
        "search_url": "https://www.aldi.us/en/products/?q={query}",
    },
]


def supplier_by_slug(slug: str) -> dict | None:
    return next((row for row in SUPPLIERS if row["slug"] == slug), None)
