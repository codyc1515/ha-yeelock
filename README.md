![Yeelock logo](https://brands.home-assistant.io/yeelock/logo.png)

# Yeelock integration for Home Assistant
Add your **Yeelock** to Home Assistant locally with BLE.

* **Lock & Unlock anytime**, you don't need your phone to be within range of your lock anymore
* **Automatic re-lock**, can re-lock automatically after a few seconds
* **Works offline**, operates locally using BLE with push notifications
* **Supports [Remote Adapters](https://www.home-assistant.io/integrations/bluetooth#remote-adapters-bluetooth-proxies) ("Bluetooth Proxies")**, to extend range of your Yeelock

Locked | Unlocked
------ | --------
![Locked](https://github.com/codyc1515/ha-yeelock/assets/50791984/fc353819-4d48-4576-beea-c6af77f4a5db)  |  ![Unlocked](https://github.com/codyc1515/ha-yeelock/assets/50791984/df5a88f2-40c3-495d-8345-531f14682822)

# Getting started
## Requirements
### QR Code (WARNING!)
- It is strongly recommended to save the QR code somewhere safe.
- If you lose the QR Code that came with your Yeelock, you will never be able to set-up your Yeelock in the app again.
- If you lose your Yeelock account details, or otherwise have issues with your Yeelock account, and you do not have your QR Code, you should assume that you will never be able to control your device again. You may be able to contact support to transfer your device over to another account but I would not count on it.
- Assume that if the QR code was lost that your device may become worthless.

### Bluetooth
You Home Assistant installation will need at least one Bluetooth adapter. Your Yeelock should be within range of your Bluetooth adapter as this integration relies on Bluetooth.

If your Yeelock is not without reach of your Bluetooth adapter, Remote Adapters (such as [ESPHome's Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html)) are supported and can extend the range of your Yeelock greatly.

### Compatible devices

* Yeelock Cabinet Lock E (Orange Stripe) / 易锁宝蓝牙抽屉柜锁E (Model: M02)

Possibly others - let me know if you find one that works.

## Installation
### HACS (recommended)
1. [Install HACS](https://hacs.xyz/docs/setup/download), if you did not already
2. [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=codyc1515&repository=ha-yeelock&category=integration)
3. Install the Yeelock integration
4. Restart Home Assistant

### Manually
Copy all files in the `custom_components`/`yeelock` folder to your Home Assistant folder `config`/`custom_components`/`yeelock`.

## Configuration
1. Setup your Yeelock first in the Yeelock app. You will need the QR code that came in the box to do this.
3. Once the integration is installed & you have restarted Home Assistant, your Yeelock will be detected & shown automatically on the `Devices and services` page.
4. You will need to input your phone's country code, phone number (without leading zero) and Yeelock account password.
5. To use the automatic re-lock, tap the button underneath the lock / unlock toggle.

## Known issues
- Signing in to this integration may sign you out of the Yeelock app automatically. We have no control over this, so you may need to sign back in to the Yeelock app afterwards. You can continue to _also_ use the Yeelock app if you would prefer, too.

## Future enhancements
Your support is welcomed.

- Add battery level sensor
- Add option to unlock automatically if battery gets too low

# Acknowledgements
- [aso824/yeehack](https://github.com/aso824/yeehack), who provided a sample Python framework for communicating with the Yeelock device
- _jdobosz_ and his post [in this thread](https://community.home-assistant.io/t/xiaomi-mijia-yeelock-integration/92331/43), for documenting how the Yeelock protocol works
- [cnrd/yeelock](https://github.com/cnrd/yeelock), for general observations on the Yeelock protocol packets
