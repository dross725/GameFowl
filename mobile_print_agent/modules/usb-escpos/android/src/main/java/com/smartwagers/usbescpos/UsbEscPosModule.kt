package com.smartwagers.usbescpos

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.os.Build
import android.util.Base64
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class UsbEscPosModule : Module() {
  companion object {
    private const val WRITE_TIMEOUT_MS = 15_000
    private const val PERMISSION_TIMEOUT_SECONDS = 30L
    private const val CHUNK_SIZE = 16_384
  }

  override fun definition() = ModuleDefinition {
    Name("UsbEscPos")

    AsyncFunction("listDevices") {
      listDevices()
    }

    AsyncFunction("printRawBase64") { identifier: String, payloadBase64: String ->
      printRawBase64(identifier, payloadBase64)
    }
  }

  private fun context(): Context =
    requireNotNull(appContext.reactContext) { "React context unavailable." }

  private fun usbManager(): UsbManager =
    context().getSystemService(Context.USB_SERVICE) as UsbManager

  private fun printableDevices(manager: UsbManager): List<UsbDevice> =
    manager.deviceList.values.filter { findBulkOut(it) != null }

  private fun safeManufacturerName(device: UsbDevice): String? =
    try {
      device.manufacturerName
    } catch (_: SecurityException) {
      null
    }

  private fun safeProductName(device: UsbDevice): String? =
    try {
      device.productName
    } catch (_: SecurityException) {
      null
    }

  private fun baseStableId(device: UsbDevice): String =
    listOf(
      device.vendorId.toString(),
      device.productId.toString(),
      safeManufacturerName(device).orEmpty(),
      safeProductName(device).orEmpty(),
    ).joinToString(":")

  private fun stableIds(devices: List<UsbDevice>): Map<UsbDevice, String> {
    val counts = devices.groupingBy(::baseStableId).eachCount()
    return devices.associateWith { device ->
      val base = baseStableId(device)
      // Identical printers cannot be distinguished without a serial number.
      // Keep a stable identity for the common single-printer case; for duplicates,
      // include the current path and require a rescan after reconnect.
      if (counts[base] == 1) base else "$base:${device.deviceName}"
    }
  }

  private fun listDevices(): List<Map<String, Any?>> {
    val manager = usbManager()
    val devices = printableDevices(manager)
    val ids = stableIds(devices)
    return devices.map { device ->
      mapOf(
        "deviceName" to device.deviceName,
        "stableId" to ids.getValue(device),
        "vendorId" to device.vendorId,
        "productId" to device.productId,
        "manufacturerName" to safeManufacturerName(device),
        "productName" to safeProductName(device),
        "deviceClass" to device.deviceClass,
        "interfaceCount" to device.interfaceCount,
      )
    }
  }

  private fun findDevice(identifier: String): UsbDevice {
    val manager = usbManager()
    val devices = printableDevices(manager)
    val ids = stableIds(devices)
    return devices.firstOrNull {
      it.deviceName == identifier || ids[it] == identifier
    } ?: throw IllegalStateException(
      "USB printer not found. Reconnect it, then scan and select it again.",
    )
  }

  private fun ensurePermission(device: UsbDevice) {
    val manager = usbManager()
    if (manager.hasPermission(device)) return

    val appContext = context()
    val action = "${appContext.packageName}.USB_PERMISSION.${System.nanoTime()}"
    val latch = CountDownLatch(1)
    var granted = false
    val receiver = object : BroadcastReceiver() {
      override fun onReceive(receiveContext: Context, intent: Intent) {
        if (intent.action != action) return
        val extraDevice = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
          intent.getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
        } else {
          @Suppress("DEPRECATION")
          intent.getParcelableExtra(UsbManager.EXTRA_DEVICE)
        }
        if (extraDevice?.deviceName == device.deviceName) {
          granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
          latch.countDown()
        }
      }
    }

    val filter = IntentFilter(action)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
      appContext.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
    } else {
      @Suppress("DEPRECATION")
      appContext.registerReceiver(receiver, filter)
    }

    try {
      val flags = PendingIntent.FLAG_UPDATE_CURRENT or
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0
      val permissionIntent = PendingIntent.getBroadcast(
        appContext,
        action.hashCode(),
        Intent(action).setPackage(appContext.packageName),
        flags,
      )
      manager.requestPermission(device, permissionIntent)
      if (!latch.await(PERMISSION_TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
        throw IllegalStateException("Timed out waiting for USB permission.")
      }
      if (!granted) {
        throw IllegalStateException("USB printer permission was denied.")
      }
    } finally {
      try {
        appContext.unregisterReceiver(receiver)
      } catch (_: IllegalArgumentException) {
        // Receiver was already removed.
      }
    }
  }

  private data class BulkOut(
    val usbInterface: UsbInterface,
    val endpoint: UsbEndpoint,
  )

  private fun findBulkOut(device: UsbDevice): BulkOut? {
    for (interfaceIndex in 0 until device.interfaceCount) {
      val usbInterface = device.getInterface(interfaceIndex)
      for (endpointIndex in 0 until usbInterface.endpointCount) {
        val endpoint = usbInterface.getEndpoint(endpointIndex)
        if (
          endpoint.type == UsbConstants.USB_ENDPOINT_XFER_BULK &&
          endpoint.direction == UsbConstants.USB_DIR_OUT
        ) {
          return BulkOut(usbInterface, endpoint)
        }
      }
    }
    return null
  }

  private fun printRawBase64(identifier: String, payloadBase64: String) {
    val payload = Base64.decode(payloadBase64, Base64.DEFAULT)
    require(payload.isNotEmpty()) { "ESC/POS payload is empty." }

    val device = findDevice(identifier)
    ensurePermission(device)
    val bulk = requireNotNull(findBulkOut(device)) {
      "The selected USB device has no bulk-OUT printer endpoint."
    }
    val manager = usbManager()
    val connection: UsbDeviceConnection = manager.openDevice(device)
      ?: throw IllegalStateException("Unable to open the selected USB printer.")

    try {
      check(connection.claimInterface(bulk.usbInterface, true)) {
        "Unable to claim the USB printer interface."
      }
      var offset = 0
      while (offset < payload.size) {
        val length = minOf(CHUNK_SIZE, payload.size - offset)
        val written = connection.bulkTransfer(
          bulk.endpoint,
          payload,
          offset,
          length,
          WRITE_TIMEOUT_MS,
        )
        check(written > 0) { "USB bulk transfer failed at byte $offset." }
        offset += written
      }
    } finally {
      try {
        connection.releaseInterface(bulk.usbInterface)
      } finally {
        connection.close()
      }
    }
  }
}
