from app.extract import classify_wall, matches_watch, products_from_html, search_url, walk_products


def test_captcha_and_login_walls_are_detected():
    assert classify_wall("https://www.samsclub.com/", "<div id='px-captcha'></div>", "") == "captcha"
    assert classify_wall("https://www.costco.com/LogonForm", "<html></html>", "Sign in password") == "login"
    assert classify_wall("https://www.webstaurantstore.com/search/butter.html", "<html>Butter $3.86</html>", "Butter") is None


def test_json_products_and_watch_filter():
    payload = {
        "products": [
            {"productName": "Unsalted Butter 4 lb", "sku": "B1", "finalPrice": 19.96, "listPrice": 21.98},
            {"productName": "Diapers jumbo", "sku": "D9", "price": 24.00},
        ]
    }
    items = walk_products(payload)
    butter = next(item for item in items if "Butter" in item["name"])
    assert butter["sku"] == "B1"
    assert butter["discount"] is True
    wanted = [item for item in items if matches_watch(item, ["butter"])]
    assert len(wanted) == 1


def test_html_script_and_search_url():
    html = '<script>{"name":"Eggs 24 ct","sku":"E1","price":5.72}</script>'
    items = products_from_html(html)
    assert items[0]["sku"] == "E1"
    url = search_url(
        {"search_url": "https://www.samsclub.com/s/{query}"},
        "unsalted butter",
    )
    assert "unsalted" in url
