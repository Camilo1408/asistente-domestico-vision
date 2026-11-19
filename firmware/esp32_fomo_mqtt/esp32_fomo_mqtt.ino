/*
 * ESP32-S3 + Edge Impulse FOMO -> MQTT
 * Cuenta objetos por clase y publica el JSON del contrato en casa/camara1/detecciones.
 *
 * Arduino IDE: placa ESP32S3 Dev Module, PSRAM = "OPI PSRAM", Partition Scheme = "Huge APP".
 * Librerías: la exportada de Edge Impulse (Arduino library), PubSubClient, ArduinoJson.
 * Basado en el ejemplo esp32_camera de la librería exportada.
 */
#include "config.h"
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "esp_camera.h"
#include "img_converters.h"
#include "edge-impulse-sdk/dsp/image/image.hpp"
#if HABILITAR_HTTP_CAPTURE
#include <WebServer.h>
WebServer http(80);
#endif

// ---------- Pines de cámara ----------
#if defined(CAMARA_XIAO_ESP32S3_SENSE)
  #define PWDN_GPIO_NUM -1
  #define RESET_GPIO_NUM -1
  #define XCLK_GPIO_NUM 10
  #define SIOD_GPIO_NUM 40
  #define SIOC_GPIO_NUM 39
  #define Y9_GPIO_NUM 48
  #define Y8_GPIO_NUM 11
  #define Y7_GPIO_NUM 12
  #define Y6_GPIO_NUM 14
  #define Y5_GPIO_NUM 16
  #define Y4_GPIO_NUM 18
  #define Y3_GPIO_NUM 17
  #define Y2_GPIO_NUM 15
  #define VSYNC_GPIO_NUM 38
  #define HREF_GPIO_NUM 47
  #define PCLK_GPIO_NUM 13
#elif defined(CAMARA_ESP32S3_EYE) || defined(CAMARA_FREENOVE_ESP32S3)
  // Verificar contra el esquema de tu placa (estos son los pines de la ESP32-S3-EYE / Freenove WROOM)
  #define PWDN_GPIO_NUM -1
  #define RESET_GPIO_NUM -1
  #define XCLK_GPIO_NUM 15
  #define SIOD_GPIO_NUM 4
  #define SIOC_GPIO_NUM 5
  #define Y9_GPIO_NUM 16
  #define Y8_GPIO_NUM 17
  #define Y7_GPIO_NUM 18
  #define Y6_GPIO_NUM 12
  #define Y5_GPIO_NUM 10
  #define Y4_GPIO_NUM 8
  #define Y3_GPIO_NUM 9
  #define Y2_GPIO_NUM 11
  #define VSYNC_GPIO_NUM 6
  #define HREF_GPIO_NUM 7
  #define PCLK_GPIO_NUM 13
#else
  #error "Selecciona un modelo de cámara en config.h"
#endif

#define CAM_W 320
#define CAM_H 240

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

static uint8_t *rgb_cam = nullptr;     // frame completo RGB888 (CAM_W x CAM_H)
static uint8_t *rgb_in = nullptr;      // frame recortado al tamaño del modelo
static uint8_t prev_muestra[(CAM_W / 8) * (CAM_H / 8)];
static bool hay_prev = false;
static unsigned long t_ultima_inferencia = 0, t_ultima_revision = 0;
static volatile bool forzar_captura = false;

// ---------- Cámara ----------
bool iniciar_camara() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM; c.pin_d1 = Y3_GPIO_NUM; c.pin_d2 = Y4_GPIO_NUM; c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM; c.pin_d5 = Y7_GPIO_NUM; c.pin_d6 = Y8_GPIO_NUM; c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM; c.pin_pclk = PCLK_GPIO_NUM; c.pin_vsync = VSYNC_GPIO_NUM;
  c.pin_href = HREF_GPIO_NUM; c.pin_sccb_sda = SIOD_GPIO_NUM; c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM; c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_QVGA;   // 320x240
  c.jpeg_quality = 12;
  c.fb_count = 1;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  return esp_camera_init(&c) == ESP_OK;
}

// Captura un frame, lo decodifica a RGB888 en rgb_cam y lo recorta/escala a la entrada del modelo en rgb_in
bool capturar_frame() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) return false;
  bool ok = fmt2rgb888(fb->buf, fb->len, PIXFORMAT_JPEG, rgb_cam);
  esp_camera_fb_return(fb);
  if (!ok) return false;
  ei::image::processing::crop_and_interpolate_rgb888(
      rgb_cam, CAM_W, CAM_H, rgb_in, EI_CLASSIFIER_INPUT_WIDTH, EI_CLASSIFIER_INPUT_HEIGHT);
  return true;
}

// Callback para el clasificador: empaqueta RGB888 en floats (el bloque Image convierte a gris si aplica)
static int ei_get_data(size_t offset, size_t length, float *out) {
  size_t px = offset * 3;
  for (size_t i = 0; i < length; i++) {
    out[i] = (rgb_in[px + 2] << 16) | (rgb_in[px + 1] << 8) | rgb_in[px];
    px += 3;
  }
  return 0;
}

// Diferencia media entre el frame actual y el anterior (muestreo 1 de cada 8 px)
int diferencia_escena() {
  int idx = 0; long suma = 0;
  for (int y = 0; y < CAM_H; y += 8)
    for (int x = 0; x < CAM_W; x += 8) {
      int p = (y * CAM_W + x) * 3;
      uint8_t g = (rgb_cam[p] + rgb_cam[p + 1] + rgb_cam[p + 2]) / 3;
      if (hay_prev) suma += abs((int)g - (int)prev_muestra[idx]);
      prev_muestra[idx++] = g;
    }
  bool tenia = hay_prev; hay_prev = true;
  return tenia ? (int)(suma / idx) : 255;
}

// ---------- Inferencia y publicación ----------
void inferir_y_publicar() {
  ei::signal_t signal;
  signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
  signal.get_data = &ei_get_data;

  ei_impulse_result_t result = {0};
  EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
  if (err != EI_IMPULSE_OK) { Serial.printf("run_classifier error %d\n", err); return; }

  int conteo[N_CLASES] = {0};
#if EI_CLASSIFIER_OBJECT_DETECTION == 1
  for (uint32_t i = 0; i < result.bounding_boxes_count; i++) {
    auto bb = result.bounding_boxes[i];
    if (bb.value < UMBRAL_CONFIANZA) continue;
    for (int c = 0; c < N_CLASES; c++)
      if (strcmp(bb.label, CLASES[c]) == 0) { conteo[c]++; break; }
  }
#endif
  int latencia = result.timing.dsp + result.timing.classification;
  Serial.printf("DSP %d ms + clasificacion %d ms = %d ms\n", result.timing.dsp, result.timing.classification, latencia);

  JsonDocument doc;   // ArduinoJson 7
  JsonObject o = doc["conteo"].to<JsonObject>();
  for (int c = 0; c < N_CLASES; c++) o[CLASES[c]] = conteo[c];   // siempre todas las clases
  doc["latencia_ms"] = latencia;
  doc["umbral"] = UMBRAL_CONFIANZA;
  char buf[512];
  size_t n = serializeJson(doc, buf, sizeof(buf));
  if (mqtt.connected()) mqtt.publish(TOPIC_DETECCIONES, (const uint8_t*)buf, n, false);
  Serial.println(buf);
}

// ---------- WiFi / MQTT ----------
void conectar_wifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("WiFi");
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) { delay(300); Serial.print("."); }
  if (WiFi.status() == WL_CONNECTED) Serial.printf("\nIP: %s\n", WiFi.localIP().toString().c_str());
  else Serial.println("\nSin WiFi, reintento luego");
}

void on_mqtt(char *topic, byte *payload, unsigned int len) {
  String msg; for (unsigned i = 0; i < len; i++) msg += (char)payload[i];
  msg.trim();
  if (String(topic) == TOPIC_CMD && msg == "capturar") forzar_captura = true;
}

void conectar_mqtt() {
  if (mqtt.connected() || WiFi.status() != WL_CONNECTED) return;
  if (mqtt.connect(MQTT_CLIENT_ID, MQTT_USER, MQTT_PASS)) {
    mqtt.subscribe(TOPIC_CMD);
    Serial.println("MQTT conectado");
  } else {
    Serial.printf("MQTT fallo rc=%d\n", mqtt.state());
  }
}

#if HABILITAR_HTTP_CAPTURE
void http_capture() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) { http.send(500, "text/plain", "sin frame"); return; }
  http.sendHeader("Cache-Control", "no-store");
  http.send_P(200, "image/jpeg", (const char*)fb->buf, fb->len);
  esp_camera_fb_return(fb);
}
#endif

void setup() {
  Serial.begin(115200);
  delay(500);
  if (!psramFound()) Serial.println("ERROR: sin PSRAM (activar OPI PSRAM)");
  rgb_cam = (uint8_t*)ps_malloc(CAM_W * CAM_H * 3);
  rgb_in = (uint8_t*)ps_malloc(EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT * 3);
  if (!rgb_cam || !rgb_in) { Serial.println("ERROR: sin memoria"); while (1) delay(1000); }
  if (!iniciar_camara()) { Serial.println("ERROR: camara no inicia"); while (1) delay(1000); }
  conectar_wifi();
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(on_mqtt);
#if HABILITAR_HTTP_CAPTURE
  http.on("/capture", http_capture);
  http.begin();
#endif
}

void loop() {
  conectar_wifi();
  conectar_mqtt();
  mqtt.loop();
#if HABILITAR_HTTP_CAPTURE
  http.handleClient();
#endif

  unsigned long ahora = millis();
  bool toca_revisar = ahora - t_ultima_revision >= REVISION_CAMBIO_MS;
  bool toca_periodica = ahora - t_ultima_inferencia >= INTERVALO_MS;
  if (!toca_revisar && !forzar_captura) return;
  t_ultima_revision = ahora;

  if (!capturar_frame()) { Serial.println("fallo captura"); return; }
  bool cambio = diferencia_escena() > UMBRAL_CAMBIO_ESCENA;
  if (forzar_captura || cambio || toca_periodica) {
    forzar_captura = false;
    inferir_y_publicar();
    t_ultima_inferencia = millis();
  }
}
