# House: YoLink fridges and Frigate cameras

YoLink talks to Home Assistant. HA posts each temperature onto http://100.116.48.120:8088/house.

The YoLink app names are already mapped:

| YoLink device | Cellar tile |
| --- | --- |
| walkin cooler | Walk-in cooler |
| prep fridge | Prep fridge |
| dessert fridge | Dessert fridge |
| soda fridge | Soda fridge |
| salad fridge | Salad fridge |
| coffee station | Coffee station |
| walk in freezer | Walk-in freezer |


After connecting YoLink in Home Assistant, run:

```bash
cd /mnt/user/appdata/resto
./scripts/install-yolink-bridge.sh
```

Home Assistant’s Overview tab is one default screen. The restaurant board is the cellar Fridges page, not that Overview.
