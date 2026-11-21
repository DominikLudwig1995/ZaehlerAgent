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
          {{ with secret "secret/data/nomad/zaehler-agent" }}OPENROUTER_API_KEY={{ .Data.data.openrouter_api_key | toJSON }}
          MQTT_USER={{ .Data.data.mqtt_user | toJSON }}
          MQTT_PASSWORD={{ .Data.data.mqtt_password | toJSON }}{{ end }}
        EOT
      }

      env {
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
