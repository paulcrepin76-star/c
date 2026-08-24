# House: YoLink fridges and Frigate cameras

The cellar already has fridge tiles, including **Wine cellar** (50–58°F). YoLink does not talk to the cellar by itself. Home Assistant does.

## First YoLink sensor

1. In the **YoLink app**, name the sensor after the box it sits in (`Wine cellar`, `Walk-in cooler`, …). That name is how we know which tile to fill.
2. Open Home Assistant: http://100.116.48.120:8123  
   First visit: create the admin user.
3. **Settings → Devices & services → Add integration → YoLink**. Sign in with the same YoLink account as the phone app. The hub and sensor should appear.
4. Open the temperature entity → cog → set the entity ID to:
   - Wine cellar → `sensor.wine_cellar_temperature`
   - Walk-in cooler → `sensor.walk_in_cooler_temperature`
   - Prep / line / pastry / bar / freezer: `sensor.prep_cooler_temperature`, `sensor.line_cooler_temperature`, `sensor.pastry_cooler_temperature`, `sensor.bar_cooler_temperature`, `sensor.walk_in_freezer_temperature`
5. If there is a humidity entity, rename it the same way with `_humidity` (`sensor.wine_cellar_humidity`).
6. On Unraid:

```bash
cd /mnt/user/appdata/resto
./scripts/install-yolink-bridge.sh
```

That copies the automation into Home Assistant and points it at the cellar API. Within about ten minutes the tile on http://100.116.48.120:8088/house should show a temperature.

A kitchen fridge on the **Wine cellar** tile will always alert (wine is 50–58°F, a walk-in is 34–40°F). Name the entity for the actual box.
