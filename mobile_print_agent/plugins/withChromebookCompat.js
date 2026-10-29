/**
 * Expo config plugin: Chromebook / ARC-friendly Android manifest.
 * - Declares touchscreen, bluetooth, usb.host as optional (required=false)
 * - Makes the main activity resizable and orientation-unlocked
 */
const {
  AndroidConfig,
  withAndroidManifest,
} = require('@expo/config-plugins');

const OPTIONAL_FEATURES = [
  'android.hardware.touchscreen',
  'android.hardware.bluetooth',
  'android.hardware.usb.host',
  'android.hardware.wifi',
];

function ensureUsesFeature(manifest, name) {
  if (!manifest.manifest['uses-feature']) {
    manifest.manifest['uses-feature'] = [];
  }
  const features = manifest.manifest['uses-feature'];
  const existing = features.find((node) => node?.$?.['android:name'] === name);
  if (existing) {
    existing.$['android:required'] = 'false';
    return;
  }
  features.push({
    $: {
      'android:name': name,
      'android:required': 'false',
    },
  });
}

function withChromebookCompat(config) {
  return withAndroidManifest(config, (config) => {
    const manifest = config.modResults;

    for (const feature of OPTIONAL_FEATURES) {
      ensureUsesFeature(manifest, feature);
    }

    const app = AndroidConfig.Manifest.getMainApplicationOrThrow(manifest);
    const activities = app.activity || [];
    for (const activity of activities) {
      const name = activity?.$?.['android:name'] || '';
      if (!name.endsWith('.MainActivity') && name !== '.MainActivity') continue;
      activity.$['android:resizeableActivity'] = 'true';
      // Unlock portrait so Chromebook windows can rotate / resize freely.
      delete activity.$['android:screenOrientation'];
    }

    return config;
  });
}

module.exports = withChromebookCompat;
