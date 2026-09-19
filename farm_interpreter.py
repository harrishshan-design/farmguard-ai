"""Farmer-friendly interpretation of FarmGuard's current, real state.

This module never reads hardware or executes device commands.  It only explains a
provided state snapshot, which keeps future voice and actuator layers safely separate.
"""
from __future__ import annotations

from typing import Any, Literal

Language = Literal["en", "ms", "ta", "zh"]

LANGUAGE_NAMES = {"en": "English", "ms": "Bahasa Melayu", "ta": "Tamil", "zh": "Chinese"}

TEXT = {
    "en": {"status":"Status", "reason":"Reason", "action":"Action", "safe":"Your farm is currently safe.", "attention":"Your farm needs attention.", "critical":"Your farm needs an urgent check.", "normal_action":"No action is needed right now.", "sensor_missing":"Some sensor information is unavailable.", "security":"Movement was detected near the farm.", "water_critical":"The water tank is critically low.", "water_low":"The water tank is getting low.", "hot":"The temperature is very high.", "soil_critical":"The soil is dangerously dry.", "soil_low":"The soil is getting dry.", "check_security":"Check the security area safely.", "refill":"Refill the tank before irrigating.", "cool":"Check shade and crop heat stress.", "irrigate":"Irrigate the crop if the soil is dry.", "check_sensor":"Check the unavailable sensor connection.", "enough_soil":"Enough water — do not irrigate now.", "dry_soil":"Dry soil — irrigation may be needed.", "enough_water":"The tank has enough water.", "low_water":"Tank is low — plan a refill.", "temp_ok":"Temperature is in a comfortable range.", "temp_hot":"Hot conditions — monitor crops.", "motion_clear":"No unusual movement detected.", "motion_seen":"Movement detected — inspect safely."},
    "ms": {"status":"Status", "reason":"Sebab", "action":"Tindakan", "safe":"Ladang anda selamat sekarang.", "attention":"Ladang anda memerlukan perhatian.", "critical":"Ladang anda perlu diperiksa segera.", "normal_action":"Tiada tindakan diperlukan sekarang.", "sensor_missing":"Sebahagian maklumat sensor tidak tersedia.", "security":"Pergerakan dikesan berhampiran ladang.", "water_critical":"Tangki air sangat rendah.", "water_low":"Air tangki semakin rendah.", "hot":"Suhu sangat tinggi.", "soil_critical":"Tanah terlalu kering.", "soil_low":"Tanah semakin kering.", "check_security":"Periksa kawasan keselamatan dengan berhati-hati.", "refill":"Isi semula tangki sebelum pengairan.", "cool":"Periksa teduhan dan tekanan haba tanaman.", "irrigate":"Siram tanaman jika tanah kering.", "check_sensor":"Periksa sambungan sensor yang tidak tersedia.", "enough_soil":"Air mencukupi — tidak perlu menyiram sekarang.", "dry_soil":"Tanah kering — pengairan mungkin diperlukan.", "enough_water":"Air dalam tangki mencukupi.", "low_water":"Tangki rendah — rancang isi semula.", "temp_ok":"Suhu berada dalam julat selesa.", "temp_hot":"Cuaca panas — pantau tanaman.", "motion_clear":"Tiada pergerakan luar biasa dikesan.", "motion_seen":"Pergerakan dikesan — periksa dengan selamat."},
    "ta": {"status":"நிலை", "reason":"காரணம்", "action":"செயல்", "safe":"உங்கள் பண்ணை தற்போது பாதுகாப்பாக உள்ளது.", "attention":"உங்கள் பண்ணைக்கு கவனம் தேவை.", "critical":"உங்கள் பண்ணையை உடனடியாகச் சரிபார்க்க வேண்டும்.", "normal_action":"இப்போது எந்த நடவடிக்கையும் தேவையில்லை.", "sensor_missing":"சில சென்சார் தகவல்கள் கிடைக்கவில்லை.", "security":"பண்ணைக்கு அருகில் அசைவு கண்டறியப்பட்டது.", "water_critical":"தண்ணீர் தொட்டி மிகவும் குறைவாக உள்ளது.", "water_low":"தொட்டி நீர் குறைந்து வருகிறது.", "hot":"வெப்பநிலை மிகவும் அதிகமாக உள்ளது.", "soil_critical":"மண் மிகவும் வறண்டுள்ளது.", "soil_low":"மண் வறண்டு வருகிறது.", "check_security":"பாதுகாப்புப் பகுதியை கவனமாகச் சரிபார்க்கவும்.", "refill":"நீர்ப்பாசனத்திற்கு முன் தொட்டியை நிரப்பவும்.", "cool":"நிழல் மற்றும் பயிர் வெப்ப அழுத்தத்தைச் சரிபார்க்கவும்.", "irrigate":"மண் வறண்டிருந்தால் பயிருக்கு நீர் பாய்ச்சவும்.", "check_sensor":"கிடைக்காத சென்சார் இணைப்பைச் சரிபார்க்கவும்.", "enough_soil":"போதுமான நீர் உள்ளது — இப்போது பாசனம் வேண்டாம்.", "dry_soil":"மண் வறண்டுள்ளது — பாசனம் தேவைப்படலாம்.", "enough_water":"தொட்டியில் போதுமான தண்ணீர் உள்ளது.", "low_water":"தொட்டி குறைவாக உள்ளது — நிரப்ப திட்டமிடுங்கள்.", "temp_ok":"வெப்பநிலை வசதியான வரம்பில் உள்ளது.", "temp_hot":"வெப்பம் அதிகம் — பயிர்களை கண்காணிக்கவும்.", "motion_clear":"வழக்கத்திற்கு மாறான அசைவு இல்லை.", "motion_seen":"அசைவு கண்டறியப்பட்டது — பாதுகாப்பாகச் சரிபார்க்கவும்."},
    "zh": {"status":"状态", "reason":"原因", "action":"建议", "safe":"您的农场目前安全。", "attention":"您的农场需要关注。", "critical":"您的农场需要立即检查。", "normal_action":"目前不需要采取行动。", "sensor_missing":"部分传感器信息不可用。", "security":"农场附近检测到移动。", "water_critical":"水箱水位极低。", "water_low":"水箱水位正在下降。", "hot":"温度非常高。", "soil_critical":"土壤严重干燥。", "soil_low":"土壤正在变干。", "check_security":"请安全检查警戒区域。", "refill":"灌溉前请补充水箱。", "cool":"请检查遮阳和作物热应激。", "irrigate":"如果土壤干燥，请给作物灌溉。", "check_sensor":"请检查不可用传感器的连接。", "enough_soil":"水分充足——现在无需灌溉。", "dry_soil":"土壤偏干——可能需要灌溉。", "enough_water":"水箱水量充足。", "low_water":"水箱水量偏低——请准备补水。", "temp_ok":"温度处于舒适范围。", "temp_hot":"天气炎热——请观察作物。", "motion_clear":"未检测到异常移动。", "motion_seen":"检测到移动——请安全检查。"},
}

def _value(value: Any, suffix: str = "") -> str:
    return "unavailable" if value is None else f"{value:g}{suffix}" if isinstance(value, (int, float)) else str(value)

def interpret_farm(sensors: dict[str, Any], decision: dict[str, Any], language: Language = "en") -> dict[str, Any]:
    t = TEXT.get(language, TEXT["en"]); issues: list[dict[str, Any]] = []
    motion, water, temp, soil = sensors.get("motion"), sensors.get("water_level"), sensors.get("temperature"), sensors.get("soil_moisture")
    ignored_optional={"uptime","soil_raw","water_raw","motion_count","pump","fan","led","reservoir_state","wifi_rssi"}
    missing = [key.replace("_", " ") for key, value in sensors.items() if value is None and key not in ignored_optional]
    if sensors.get("water_raw") is not None and "water level" in missing: missing.remove("water level")
    if motion is True: issues.append({"rank":1,"severity":"CRITICAL","reason":t["security"],"action":t["check_security"]})
    if water is not None and water < 12: issues.append({"rank":2,"severity":"CRITICAL","reason":t["water_critical"],"action":t["refill"]})
    elif water is not None and water < 25: issues.append({"rank":7,"severity":"WARNING","reason":t["water_low"],"action":t["refill"]})
    if temp is not None and temp >= 40: issues.append({"rank":3,"severity":"CRITICAL","reason":t["hot"],"action":t["cool"]})
    if soil is not None and soil < 15: issues.append({"rank":4,"severity":"CRITICAL","reason":t["soil_critical"],"action":t["irrigate"]})
    elif soil is not None and soil < 30: issues.append({"rank":6,"severity":"WARNING","reason":t["soil_low"],"action":t["irrigate"]})
    if missing: issues.append({"rank":5,"severity":"WARNING","reason":t["sensor_missing"],"action":t["check_sensor"]})
    issues.sort(key=lambda item: item["rank"])
    top = issues[0] if issues else {"severity":"NORMAL","reason":t["safe"],"action":t["normal_action"]}
    severity = top["severity"]
    status = t["critical"] if severity == "CRITICAL" else t["attention"] if severity == "WARNING" else t["safe"]
    water_display=_value(water,'%') if water is not None else f"raw {_value(sensors.get('water_raw'))}" if sensors.get("water_raw") is not None else "unavailable"
    reasons = [item["reason"] for item in issues[:3]] or [f"Soil {_value(soil,'%')}, water {water_display}, temperature {_value(temp,'°C')}, security {'clear' if motion is False else 'unavailable'}." ]
    actions = list(dict.fromkeys(item["action"] for item in issues))[:3] or [t["normal_action"]]
    meanings = {
        "soil": t["enough_soil"] if soil is not None and soil >= 30 else t["dry_soil"] if soil is not None else t["sensor_missing"],
        "water": t["enough_water"] if water is not None and water >= 25 else t["low_water"] if water is not None else f"Raw water reading {_value(sensors.get('water_raw'))} — percentage calibration unavailable." if sensors.get("water_raw") is not None else t["sensor_missing"],
        "temperature": t["temp_ok"] if temp is not None and temp < 35 else t["temp_hot"] if temp is not None else t["sensor_missing"],
        "motion": t["motion_clear"] if motion is False else t["motion_seen"] if motion is True else t["sensor_missing"],
    }
    reason = " ".join(reasons)
    return {"priority":severity,"status":status,"reason":reason,"actions":actions,"recommendation":actions,
            "meanings":meanings,"daily_summary":f"{status} {reason} {actions[0]}",
            "response":f'{t["status"]}: {status}\n{t["reason"]}: {reason}\n{t["action"]}: {actions[0]}',
            "language":language,"language_name":LANGUAGE_NAMES.get(language,"English")}

def answer_question(question: str, sensors: dict[str, Any], decision: dict[str, Any], language: Language = "en") -> dict[str, Any]:
    interpretation = interpret_farm(sensors, decision, language); q = question.lower(); t = TEXT.get(language,TEXT["en"])
    soil, water, motion, temp = sensors.get("soil_moisture"), sensors.get("water_level"), sensors.get("motion"), sensors.get("temperature")
    if any(word in q for word in ("water", "irrig", "soil", "tanah", "நீர்", "水")):
        reason=f"Soil {_value(soil,'%')}; tank {_value(water,'%')}."; action=t["irrigate"] if soil is not None and soil < 30 else t["normal_action"]
    elif any(word in q for word in ("safe", "security", "motion", "leave", "selamat", "பாதுகாப்பு", "安全")):
        reason=f"Motion: {'detected' if motion is True else 'clear' if motion is False else 'unavailable'}."; action=t["check_security"] if motion else t["normal_action"]
    elif any(word in q for word in ("sensor", "problem", "working", "சென்சார்", "传感器")):
        ignored={"uptime","soil_raw","water_raw","motion_count","pump","fan","led","reservoir_state","wifi_rssi"}
        missing=[key.replace("_"," ") for key,value in sensors.items() if value is None and key not in ignored]
        if sensors.get("water_raw") is not None and "water level" in missing: missing.remove("water level")
        reason="Unavailable: "+(", ".join(missing) if missing else "none")+"."; action=t["check_sensor"] if missing else t["normal_action"]
    elif any(word in q for word in ("crop", "hot", "temperature", "tanaman", "பயிர்", "作物")):
        reason=f"Temperature {_value(temp,'°C')}; soil {_value(soil,'%')}."; action=t["cool"] if temp is not None and temp >= 35 else interpretation["actions"][0]
    else:
        reason, action = interpretation["reason"], interpretation["actions"][0]
    return {**interpretation,"reason":reason,"actions":[action],"response":f'{t["status"]}: {interpretation["status"]}\n{t["reason"]}: {reason}\n{t["action"]}: {action}'}

def prepare_device_recommendation(command: str) -> dict[str, Any]:
    """Future actuator boundary: this function never sends a device command."""
    return {"recommendation":command,"safety_verified":False,"requires_user_confirmation":True,
            "device_confirmation_required":True,"executed":False}
