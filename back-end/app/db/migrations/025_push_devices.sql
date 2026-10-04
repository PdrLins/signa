-- ============================================================================
-- 025_push_devices.sql — iOS push notifications (APNs)
-- ============================================================================
-- One row per app install that allowed notifications. The iOS app sends its
-- APNs device token after sign-in (POST /api/v1/notifications/devices) and
-- removes it on sign-out (DELETE). A token belongs to one user: registering
-- it from another account moves it. Tokens Apple reports as invalid are
-- disabled (disabled_at). Delivery reuses notification_prefs and
-- notification_deliveries (dedupe keys prefixed "push:"). Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS push_devices (
    token         VARCHAR(200) PRIMARY KEY,           -- APNs device token (hex)
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform      VARCHAR(8)  NOT NULL DEFAULT 'ios' CHECK (platform IN ('ios')),
    environment   VARCHAR(12) NOT NULL DEFAULT 'production' CHECK (environment IN ('sandbox', 'production')),
    app_version   VARCHAR(32),
    device_name   VARCHAR(80),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_push_devices_user ON push_devices (user_id) WHERE disabled_at IS NULL;

DROP TRIGGER IF EXISTS push_devices_updated_at ON push_devices;
CREATE TRIGGER push_devices_updated_at BEFORE UPDATE ON push_devices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE public.push_devices ENABLE ROW LEVEL SECURITY;

INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.push_all', 'premium', 'Every push notification type (free: price alerts, dividends, earnings, report updates)'),
  ('feature.all_widgets', 'premium', 'Every home-screen and lock-screen widget (free: 1)')
ON CONFLICT (key) DO NOTHING;
