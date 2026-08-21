from app.names import pretty_item


def test_pretty_item_strips_pos_noise():
    name, pack = pretty_item("2 89712 1 1 BAG Co e Decaf Reserve WB 5 lb Stan's ' 1 60.50 60.5")
    assert name == "Decaf Reserve Coffee Beans"
    assert pack == "5 lb bag"
    name, pack = pretty_item('5147 10" Golden Hoagie 6ct Unsl 10 3.02 30.20')
    assert name == "Golden Hoagie Rolls"
    assert pack == '10", 6 count'
    name, pack = pretty_item("Member's Mark Baby Swiss Cheese Slices 2 lbs.")
    assert name == "Baby Swiss Cheese Slices"
    assert pack == "2 lb"
    name, pack = pretty_item("Member's Mark Heavy Whipping Cream 64 fl. oz. Qty 8")
    assert name == "Heavy Whipping Cream"
    assert pack == "64 fl oz"
    name, pack = pretty_item("S27 EACH @ EJEF 9.94")
    assert name == ""
