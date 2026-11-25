import logging
from django.utils import timezone

logger = logging.getLogger(__name__)

DETECTOR_VERSION = 'v1'
IMPOSSIBLE_SPEED_KMH = 180.0
CONFIRMED_SPEED_KMH = 500.0
MIN_JUMP_METERS = 1000.0
CLONE_CONTACT_MIN_DISTANCE_M = 200.0


def evaluate_visit_gps_integrity(visit, user, contact, stage='start', client_telemetry=None):
    """
    Server-side, non-blocking GPS/GBS integrity analyzer.
    Evaluates technically supported web/server signals without ever blocking
    the normal visit workflow, altering distance rules, or exposing warnings to the rep.

    Statuses:
    - 'normal': No suspicious signals detected.
    - 'suspicious': One or more anomaly signals detected.
    - 'confirmed_manipulation': Multiple high-confidence manipulation signals concur.
    - 'undetermined': Coordinates unavailable or analyzer could not evaluate.
    """
    now = timezone.now()
    try:
        if visit.latitude is None or visit.longitude is None:
            visit.gps_integrity_status = 'undetermined'
            visit.gps_integrity_checked_at = now
            visit.gps_suspicion_signals = []
            visit.gps_suspicion_reason = 'لم يتم توفير إحداثيات GPS لتقييم نزاهة الموقع.'
            visit.gps_integrity_context = {'stage': stage}
            visit.gps_detector_version = DETECTOR_VERSION
            return visit

        from activities.models import Visit
        from activities.services import calculate_haversine_distance

        signals = []
        reasons = []
        context = {
            'stage': stage,
            'lat': float(visit.latitude),
            'lng': float(visit.longitude),
            'accuracy': float(visit.device_accuracy) if visit.device_accuracy is not None else None,
            'distance_m': float(visit.distance) if visit.distance is not None else None,
        }
        high_confidence_speed = False

        # 1. Accuracy anomaly
        if visit.device_accuracy is not None:
            acc = float(visit.device_accuracy)
            if acc <= 0.0 or acc > 5000.0:
                signals.append('invalid_or_zero_accuracy')
                reasons.append(f'قيمة دقة الجهاز غير طبيعية ({acc:.1f}م).')

        # 2. Impossible travel speed compared to user's prior visit on the same day
        if user and getattr(user, 'pk', None):
            prior_qs = Visit.objects.filter(
                owner=user,
                date=visit.date,
                latitude__isnull=False,
                longitude__isnull=False,
            )
            if visit.pk:
                prior_qs = prior_qs.exclude(pk=visit.pk)
            prior = prior_qs.order_by('-ended_at', '-started_at', '-updated_at').first()
            if prior:
                prior_ts = prior.ended_at or prior.started_at or prior.updated_at
                if prior_ts:
                    delta_sec = (now - prior_ts).total_seconds()
                    if 1.0 <= delta_sec <= 43200.0:
                        jump_m = calculate_haversine_distance(
                            visit.latitude, visit.longitude, prior.latitude, prior.longitude
                        )
                        if jump_m is not None and jump_m >= MIN_JUMP_METERS:
                            speed_kmh = (jump_m / 1000.0) / (delta_sec / 3600.0)
                            if speed_kmh > IMPOSSIBLE_SPEED_KMH:
                                signals.append('impossible_travel_speed')
                                reasons.append(
                                    f'انتقال غير منطقي بين زيارتين ({jump_m / 1000.0:.1f} كم خلال {int(delta_sec)} ثانية ≈ {speed_kmh:.0f} كم/س).'
                                )
                                context['prior_visit_id'] = prior.pk
                                context['jump_km'] = round(jump_m / 1000.0, 2)
                                context['delta_sec'] = int(delta_sec)
                                context['implied_speed_kmh'] = round(speed_kmh, 1)
                                if speed_kmh > CONFIRMED_SPEED_KMH and jump_m > 5000.0:
                                    high_confidence_speed = True

        # 3. Exact coordinate cloning across distinct distant contacts
        if user and getattr(user, 'pk', None) and contact and getattr(contact, 'pk', None):
            clone_qs = Visit.objects.filter(
                owner=user,
                latitude=visit.latitude,
                longitude=visit.longitude,
            ).exclude(contact=contact).select_related('contact')
            if visit.pk:
                clone_qs = clone_qs.exclude(pk=visit.pk)
            cloned_visit = clone_qs.order_by('-created_at').first()
            if cloned_visit:
                c_lat = visit.customer_latitude_snapshot if visit.customer_latitude_snapshot is not None else getattr(contact, 'latitude', None)
                c_lng = visit.customer_longitude_snapshot if visit.customer_longitude_snapshot is not None else getattr(contact, 'longitude', None)
                oc_lat = cloned_visit.customer_latitude_snapshot if cloned_visit.customer_latitude_snapshot is not None else getattr(cloned_visit.contact, 'latitude', None)
                oc_lng = cloned_visit.customer_longitude_snapshot if cloned_visit.customer_longitude_snapshot is not None else getattr(cloned_visit.contact, 'longitude', None)
                dist_between_contacts = None
                if c_lat is not None and c_lng is not None and oc_lat is not None and oc_lng is not None:
                    dist_between_contacts = calculate_haversine_distance(c_lat, c_lng, oc_lat, oc_lng)
                if dist_between_contacts is None or dist_between_contacts > CLONE_CONTACT_MIN_DISTANCE_M:
                    signals.append('exact_coordinate_clone')
                    reasons.append(
                        f'تطابق تام في الإحداثيات مع زيارة لعميل آخر (#{cloned_visit.serial_num}).'
                    )
                    context['cloned_visit_id'] = cloned_visit.pk

        # 4. Optional browser geolocation timestamp drift
        if isinstance(client_telemetry, dict):
            ts_ms = client_telemetry.get('coords_timestamp_ms')
            if ts_ms is not None:
                try:
                    drift_sec = abs(now.timestamp() - (float(ts_ms) / 1000.0))
                    if drift_sec > 600.0:
                        signals.append('stale_or_drifted_timestamp')
                        reasons.append(f'تفاوت زمني ملحوظ في طابع إحداثيات المتصفح ({int(drift_sec)} ثانية).')
                        context['timestamp_drift_sec'] = int(drift_sec)
                except (TypeError, ValueError):
                    pass

        if high_confidence_speed and 'exact_coordinate_clone' in signals:
            status = 'confirmed_manipulation'
        elif signals:
            status = 'suspicious'
        else:
            status = 'normal'

        visit.gps_integrity_status = status
        visit.gps_integrity_checked_at = now
        visit.gps_suspicion_signals = signals
        visit.gps_suspicion_reason = ' | '.join(reasons) if reasons else ''
        visit.gps_integrity_context = context
        visit.gps_detector_version = DETECTOR_VERSION
        return visit

    except Exception as exc:
        logger.warning("GPS integrity evaluation failed for visit=%s: %s", getattr(visit, 'pk', None), exc)
        visit.gps_integrity_status = 'undetermined'
        visit.gps_integrity_checked_at = now
        visit.gps_suspicion_signals = []
        visit.gps_suspicion_reason = 'تعذر إتمام فحص نزاهة الموقع.'
        visit.gps_integrity_context = {'stage': stage, 'error': True}
        visit.gps_detector_version = DETECTOR_VERSION
        return visit
