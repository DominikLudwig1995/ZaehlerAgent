# zaehler-agent (docs: README). Reads the gas and water meter cameras with a vision model and publishes the values
# to Home Assistant over MQTT. One instance is enough: it keeps no state (the last values are retained MQTT messages).
#   deploy/nomad-deploy.sh deploy/nomad.hcl registry.example.com/homelab/zaehler-agent:<tag>
variable "image" {
  type = string
}

job "zaehler-agent" {
  datacenters = ["homelab"]
  type        = "service"

  update {
    max_parallel      = 1
    min_healthy_time  = "20s"
    healthy_deadline  = "10m"
    progress_deadline = "15m"
    auto_revert       = true
  }

  group "app" {
    count = 1

    # History and the settings edited in the UI live in the allocation directory (/alloc/data). A sticky,
    # migrating ephemeral disk carries them over to the next allocation of an update or a reschedule.
    # A node that is lost for good loses them (the config below is the fallback).
    ephemeral_disk {
      sticky  = true
      migrate = true
      size    = 300
    }

    network {
      port "http" {
        to = 8000
      }
    }

    restart {
      attempts = 3
      interval = "5m"
      delay    = "15s"
      mode     = "delay"
    }

    reschedule {
      delay          = "30s"
      delay_function = "exponential"
      max_delay      = "5m"
      unlimited      = true
    }

    service {
      name     = "zaehler-agent"
      provider = "consul"
      port     = "http"
      tags = [
        "prometheus-scrape", # Prometheus finds /metrics through Consul
        "traefik.enable=true",
        "traefik.http.routers.zaehler.rule=Host(`zaehler.example.com`)",
        "traefik.http.routers.zaehler.entrypoints=websecure",
        "traefik.http.routers.zaehler.tls=true",
        # UI can set values and trigger paid model calls: login (tinyauth) and LAN only.
        "traefik.http.routers.zaehler.middlewares=crowdsec-bouncer@file,local-filter@file,tinyauth-check@file",
      ]

      check {
        type     = "http"
        path     = "/healthz"
        interval = "30s"
        timeout  = "3s"
      }
    }

    task "app" {
      driver = "docker"

      # Workload identity: reads only secret/nomad/zaehler-agent (see your Vault and Nomad JWT setup).
      vault {}

      config {
        image = var.image
        ports = ["http"]

        # Container logs go to journald: Alloy ships them to Loki (label nomad_job).
        logging {
          type = "journald"
          config {
            tag = "${NOMAD_JOB_NAME}"
          }
        }
      }

      # OPENROUTER_API_KEY and the MQTT login come from Vault (secret/nomad/zaehler-agent).
      template {
        destination = "secrets/zaehler.env"
        env         = true
        data        = <<-EOT
          {{ with secret "secret/data/nomad/zaehler-agent" }}LLM_API_KEY={{ .Data.data.openrouter_api_key | toJSON }}
          MQTT_USER={{ .Data.data.mqtt_user | toJSON }}
          MQTT_PASSWORD={{ .Data.data.mqtt_password | toJSON }}{{ end }}
        EOT
      }

      # The homelab meters (camera addresses, crops): the config of this installation, inline.
      template {
        destination = "local/config.yml"
        data        = <<-EOT
          # Homelab configuration (rendered into the Nomad job). Other people: start from config/config.example.yml.
          mqtt:
            topic_prefix: zaehler-agent
          # The two AI-on-the-edge cameras (ESP32-CAM). image_url is the picture the camera has already rotated and aligned
          # to its reference image, so the digit row is always in the same place: crop is [x0, y0, x1, y1] in that picture.
          # max_rate_per_hour (m3/h) is the most the counter can plausibly advance; a reading above it is thrown away.
          # initial_value is only used until the first value is stored in MQTT (retained), then the stored one wins.
          meters:
            - name: gas
              title: Gaszähler
              kind: gas
              image_url: http://192.0.2.10/img_tmp/alg.jpg
              device_json_url: http://192.0.2.10/json
              live_url: http://192.0.2.10/capture
              light_on_url: http://192.0.2.10/lighton
              light_off_url: http://192.0.2.10/lightoff
              integer_digits: 4
              decimals: 3
              crop: [10, 15, 640, 130]
              max_rate_per_hour: 4.0
              initial_value: 3598.66
            - name: wasser
              title: Wasserzähler
              kind: water
              image_url: http://192.0.2.11/img_tmp/raw.jpg   # raw: the aligned picture cuts off the last wheel
              device_json_url: http://192.0.2.11/json
              live_url: http://192.0.2.11/capture
              light_on_url: http://192.0.2.11/lighton
              light_off_url: http://192.0.2.11/lightoff
              integer_digits: 5
              decimals: 3
              crop: [60, 0, 640, 200]
              max_rate_per_hour: 1.5
              initial_value: 150.21
        EOT
      }

      env {
        CONFIG_FILE      = "/local/config.yml"
        # Settings saved in the UI (settings.json) win over the config below. "Reset" in the UI goes back to it.
        DATA_DIR         = "/alloc/data"
        MQTT_HOST        = "192.0.2.20"
        INTERVAL_SECONDS = "1800"
        MODELS           = "openai/gpt-4o-mini,qwen/qwen3-vl-30b-a3b-instruct"
      }

      resources {
        cpu        = 100
        memory     = 128
        memory_max = 256
      }
    }
  }
}
