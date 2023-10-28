![Company logo](https://www.yeeloc.com/wp-content/themes/yisuobao/assets/image/banner.svg)

# Yeelock integration for Home Assistant
## Compatible devices

* Yeelock Cabinet Lock E (Orange Stripe) / 易锁宝蓝牙抽屉柜锁E (Model: M02)

Possibly others - let me know if you find one that works.

## Getting started
Your Yeelock devices should be detected automatically by Home Assistant and be able to be configured from the UI.

However, you will still need to obtain the *ble_sign_key* to connect with your device first. You can do this by MITM the Yeelock app and looking for the *ble_sign_key* in the server API response. Hopefully we can make this more straightforward in the future as the API itself is extremely simple. Any help welcomed.

## Installation
You will need to have a Bluetooth dongle or Bluetooth Proxies connected and within range of your Yeelock device.

### HACS (recommended)
1. [Install HACS](https://hacs.xyz/docs/setup/download), if you did not already
2. [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=codyc1515&repository=hacs_yeelock&category=integration)
3. Install the Yeelock integration
4. Restart Home Assistant

### Manually
Copy all files in the custom_components/hacs_yeelock folder to your Home Assistant folder *config/custom_components/yeelock*.

## Known issues

* Labels don't show when using the config_flow (the last, and empty, field is the *ble_sign_key*)

## Future enhancements
Your support is welcomed.

* Integration with the Yeelock Cloud (App) API to obtain the key automatically

## Acknowledgements
- [aso824/yeehack](https://github.com/aso824/yeehack), who provided a sample Python framework for communicating with the Yeelock device
- _jdobosz_ and his post [in this thread](https://community.home-assistant.io/t/xiaomi-mijia-yeelock-integration/92331/43), for documenting how the Yeelock protocol works
- [cnrd/yeelock](https://github.com/cnrd/yeelock), for general observations on the Yeelock protocol packets
