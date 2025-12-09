import streamlit as st
import pandas as pd
import numpy as np
import json
import time
import queue
import threading
from datetime import datetime, timedelta
import plotly.graph_objs as go
import plotly.express as px
import paho.mqtt.client as mqtt
import socket

# ==================== KONFIGURASI ====================
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC_SENSOR = "iot/streetlight"
MQTT_TOPIC_CONTROL = "iot/streetlight/control"

# UI constants
MAX_POINTS = 200

# ==================== GLOBAL QUEUE ====================
GLOBAL_MQ = queue.Queue()

# ==================== STREAMLIT PAGE SETUP ====================
st.set_page_config(
    page_title="Smart Streetlight Dashboard",
    page_icon="💡",
    layout="wide"
)

st.title("💡 SMART STREETLIGHT MONITORING SYSTEM")

# ==================== SESSION STATE INIT ====================
if "msg_queue" not in st.session_state:
    st.session_state.msg_queue = GLOBAL_MQ

if "logs" not in st.session_state:
    st.session_state.logs = []

if "last_data" not in st.session_state:
    st.session_state.last_data = None

if "mqtt_thread_started" not in st.session_state:
    st.session_state.mqtt_thread_started = False

if "mqtt_connected" not in st.session_state:
    st.session_state.mqtt_connected = False

if "connection_status" not in st.session_state:
    st.session_state.connection_status = "❌ TIDAK TERKONEKSI"

if "connection_error" not in st.session_state:
    st.session_state.connection_error = ""

if "manual_connect_clicked" not in st.session_state:
    st.session_state.manual_connect_clicked = False

if "broker_test_result" not in st.session_state:
    st.session_state.broker_test_result = None

# ==================== FUNGSI TEST KONEKSI ====================
def test_broker_connection():
    """Test connection to MQTT broker"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((MQTT_BROKER, MQTT_PORT))
        sock.close()
        return result == 0, None
    except Exception as e:
        return False, str(e)

# ==================== MQTT CALLBACKS ====================
def _on_connect(client, userdata, flags, rc):
    """Callback ketika koneksi MQTT berhasil/gagal"""
    if rc == 0:
        client.subscribe(MQTT_TOPIC_SENSOR)
        GLOBAL_MQ.put({
            "_type": "status", 
            "connected": True, 
            "message": f"✅ Terhubung ke broker",
            "ts": time.time()
        })
    else:
        error_messages = {
            1: "Incorrect protocol version",
            2: "Invalid client identifier",
            3: "Server unavailable",
            4: "Bad username or password",
            5: "Not authorized"
        }
        error_msg = error_messages.get(rc, f"Error code: {rc}")
        GLOBAL_MQ.put({
            "_type": "status",
            "connected": False,
            "message": f"❌ Koneksi gagal: {error_msg}",
            "ts": time.time()
        })

def _on_message(client, userdata, msg):
    """Callback ketika menerima pesan MQTT"""
    try:
        payload = msg.payload.decode('utf-8', errors='ignore')
        
        # Parse data dari ESP32 (format: {timestamp;intensity;voltage})
        if payload.startswith("{") and payload.endswith("}"):
            clean_payload = payload[1:-1]
            parts = clean_payload.split(";")
            
            if len(parts) == 3:
                timestamp_str = parts[0].strip()
                intensity_str = parts[1].strip()
                voltage_str = parts[2].strip()
                
                # Parse values
                try:
                    intensity = float(intensity_str)
                except:
                    intensity = None
                
                try:
                    voltage = float(voltage_str)
                except:
                    voltage = None
                
                # Parse timestamp
                try:
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                except:
                    timestamp = datetime.now()
                
                # Determine states
                if voltage == 0.0:
                    relay_state = "MATI"
                    lamp_state = "MENYALA"
                elif voltage == 220.0:
                    relay_state = "AKTIF"
                    lamp_state = "MATI"
                else:
                    relay_state = "UNKNOWN"
                    lamp_state = "UNKNOWN"
                
                # Push to queue
                GLOBAL_MQ.put({
                    "_type": "sensor",
                    "data": {
                        "timestamp": timestamp,
                        "intensity": intensity,
                        "voltage": voltage,
                        "relay_state": relay_state,
                        "lamp_state": lamp_state
                    },
                    "ts": time.time()
                })
                
    except Exception as e:
        GLOBAL_MQ.put({
            "_type": "error",
            "message": f"Error parsing MQTT message: {str(e)}",
            "ts": time.time()
        })

def _on_disconnect(client, userdata, rc):
    """Callback ketika terputus dari MQTT"""
    GLOBAL_MQ.put({
        "_type": "status",
        "connected": False,
        "message": f"⚠️ Terputus dari broker (rc={rc})",
        "ts": time.time()
    })

# ==================== MQTT WORKER THREAD ====================
def start_mqtt_worker():
    """Start MQTT worker thread"""
    def worker():
        client = None
        while True:
            try:
                # Create new client
                client_id = f"streetlight-dashboard-{int(time.time())}"
                client = mqtt.Client(client_id=client_id)
                client.on_connect = _on_connect
                client.on_message = _on_message
                client.on_disconnect = _on_disconnect
                
                # Connect
                client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                
                # Start loop
                client.loop_forever()
                
            except Exception as e:
                error_msg = f"❌ Connection error: {str(e)}"
                GLOBAL_MQ.put({
                    "_type": "error",
                    "message": error_msg,
                    "ts": time.time()
                })
                
                # Cleanup
                if client:
                    try:
                        client.loop_stop()
                        client.disconnect()
                    except:
                        pass
                
                # Wait before retry
                time.sleep(5)
    
    if not st.session_state.mqtt_thread_started:
        t = threading.Thread(target=worker, daemon=True, name="mqtt_worker")
        t.start()
        st.session_state.mqtt_thread_started = True
        return True
    return False

# ==================== PROCESS QUEUE ====================
def process_queue():
    """Process incoming messages from MQTT queue"""
    updated = False
    q = st.session_state.msg_queue
    
    while not q.empty():
        try:
            item = q.get_nowait()
            item_type = item.get("_type")
            
            if item_type == "status":
                # Update connection status
                st.session_state.mqtt_connected = item.get("connected", False)
                st.session_state.connection_status = item.get("message", "")
                updated = True
                
            elif item_type == "error":
                # Show error message
                st.session_state.connection_error = item.get("message", "")
                updated = True
                
            elif item_type == "sensor":
                # Process sensor data
                data = item.get("data", {})
                
                row = {
                    "timestamp": data.get("timestamp", datetime.now()),
                    "intensity": data.get("intensity"),
                    "voltage": data.get("voltage"),
                    "relay_state": data.get("relay_state"),
                    "lamp_state": data.get("lamp_state"),
                    "source": "MQTT REAL"
                }
                
                # Add to logs
                st.session_state.logs.append(row)
                st.session_state.last_data = row
                
                # Keep logs bounded
                if len(st.session_state.logs) > 5000:
                    st.session_state.logs = st.session_state.logs[-5000:]
                
                updated = True
                
        except queue.Empty:
            break
        except Exception as e:
            st.error(f"Error processing queue: {str(e)}")
    
    return updated

# ==================== FUNGSI UTILITAS ====================
def calculate_statistics():
    """Calculate statistics from logs"""
    if not st.session_state.logs:
        return {
            "avg_intensity": 0,
            "avg_voltage": 0,
            "lamp_on_percentage": 0,
            "total_data": 0,
            "latest_timestamp": "N/A"
        }
    
    df = pd.DataFrame(st.session_state.logs)
    
    if df.empty:
        return {
            "avg_intensity": 0,
            "avg_voltage": 0,
            "lamp_on_percentage": 0,
            "total_data": 0,
            "latest_timestamp": "N/A"
        }
    
    # Basic stats
    avg_intensity = df["intensity"].mean() if "intensity" in df.columns and not df["intensity"].isna().all() else 0
    avg_voltage = df["voltage"].mean() if "voltage" in df.columns and not df["voltage"].isna().all() else 0
    
    # Lamp on percentage
    if "lamp_state" in df.columns:
        lamp_on_count = (df["lamp_state"] == "MENYALA").sum()
        lamp_on_percentage = (lamp_on_count / len(df)) * 100 if len(df) > 0 else 0
    else:
        lamp_on_percentage = 0
    
    # Latest timestamp
    latest_timestamp = df["timestamp"].max() if "timestamp" in df.columns else "N/A"
    if isinstance(latest_timestamp, datetime):
        latest_timestamp = latest_timestamp.strftime("%H:%M:%S")
    
    return {
        "avg_intensity": round(avg_intensity, 1),
        "avg_voltage": round(avg_voltage, 1),
        "lamp_on_percentage": round(lamp_on_percentage, 1),
        "total_data": len(df),
        "latest_timestamp": latest_timestamp
    }

def create_intensity_gauge(value):
    """Create gauge chart for light intensity"""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title={"text": "INTENSITAS CAHAYA", "font": {"size": 16}},
        domain={"x": [0, 1], "y": [0, 1]},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "#FFA500"},
            "steps": [
                {"range": [0, 30], "color": "#4CAF50", "name": "Gelap"},
                {"range": [30, 70], "color": "#FFC107", "name": "Sedang"},
                {"range": [70, 100], "color": "#2196F3", "name": "Terang"}
            ],
            "threshold": {
                "line": {"color": "red", "width": 4},
                "thickness": 0.75,
                "value": 50
            }
        }
    ))
    
    fig.update_layout(height=250, margin=dict(t=50, b=50, l=50, r=50))
    return fig

# ==================== SIDEBAR ====================
with st.sidebar:
    st.title("⚙️ KONTROL KONEKSI")
    
    # Status Connection
    st.subheader("🔗 STATUS KONEKSI")
    
    status_col1, status_col2 = st.columns([1, 3])
    with status_col1:
        if st.session_state.mqtt_connected:
            st.success("✅")
        else:
            st.error("❌")
    
    with status_col2:
        st.write(f"**Status:** {st.session_state.connection_status}")
        if st.session_state.connection_error:
            st.error(st.session_state.connection_error)
    
    # Connection Buttons
    st.markdown("---")
    st.subheader("🔄 KONTROL MQTT")
    
    col_connect, col_test = st.columns(2)
    
    with col_connect:
        if st.button("🔗 Sambungkan", use_container_width=True, type="primary"):
            st.session_state.manual_connect_clicked = True
            with st.spinner("Menghubungkan ke MQTT broker..."):
                if start_mqtt_worker():
                    st.success("MQTT worker dimulai")
                else:
                    st.info("MQTT worker sudah berjalan")
            time.sleep(1)
            st.rerun()
    
    with col_test:
        if st.button("🧪 Test Broker", use_container_width=True):
            with st.spinner("Testing koneksi ke broker..."):
                success, error = test_broker_connection()
                if success:
                    st.success("✅ Broker dapat diakses")
                    st.session_state.broker_test_result = "✅ SUCCESS"
                else:
                    st.error(f"❌ Broker tidak dapat diakses: {error}")
                    st.session_state.broker_test_result = "❌ FAILED"
    
    # Data Control
    st.markdown("---")
    st.subheader("📊 KONTROL DATA")
    
    if st.button("🗑️ Reset Data", use_container_width=True):
        st.session_state.logs = []
        st.session_state.last_data = None
        st.success("Data telah direset")
        st.rerun()
    
    if st.button("🔄 Refresh Status", use_container_width=True):
        st.rerun()
    
    # System Info
    st.markdown("---")
    st.subheader("📋 INFORMASI SISTEM")
    
    with st.expander("Konfigurasi ESP32"):
        st.code(f"""
// WiFi Configuration
const char* ssid = "labITDepan";
const char* password = "rahasia2025";

// MQTT Configuration
const char* mqtt_server = "{MQTT_BROKER}";
const int mqtt_port = {MQTT_PORT};
const char* topic = "{MQTT_TOPIC_SENSOR}";

// Format Data:
// {{timestamp;intensity;voltage}}
// Contoh: {{2024-01-01 12:30:45;35;220.0}}
        """)
    
    with st.expander("Troubleshooting"):
        st.markdown("""
        **Jika tidak ada data:**
        1. Buka Serial Monitor ESP32 (115200 baud)
        2. Cek pesan "✓ WiFi connected!"
        3. Cek pesan "✓ MQTT connected!"
        4. Cek pesan "📤 MQTT Sent: {...}"
        5. Test di MQTT client online
        """)

# ==================== PROCESS QUEUE ====================
process_queue()

# ==================== MAIN DASHBOARD ====================
# Status Banner
if not st.session_state.mqtt_connected:
    st.error("""
    ⚠️ **MQTT TIDAK TERKONEKSI!** 
    
    Silakan klik tombol "Sambungkan" di sidebar untuk menghubungkan ke broker MQTT.
    
    **Pastikan:**
    1. ESP32 menyala dan terhubung ke WiFi
    2. ESP32 mengirim data ke topic: `iot/streetlight`
    3. Format data: `{timestamp;intensity;voltage}`
    """)
else:
    st.success("✅ **TERHUBUNG KE MQTT BROKER** - Menunggu data dari ESP32...")

# ==================== METRICS CARDS ====================
st.header("📊 STATUS REAL-TIME")

if st.session_state.last_data:
    data = st.session_state.last_data
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        intensity = data.get("intensity")
        if intensity is not None:
            if intensity < 30:
                color = "🟢"
                status_text = "GELAP"
            elif intensity < 70:
                color = "🟡"
                status_text = "SEDANG"
            else:
                color = "🔵"
                status_text = "TERANG"
            
            st.metric(
                label=f"{color} Intensitas Cahaya",
                value=f"{intensity:.1f}%",
                delta=status_text,
                delta_color="off"
            )
        else:
            st.metric("Intensitas Cahaya", "N/A")
    
    with col2:
        voltage = data.get("voltage")
        relay_state = data.get("relay_state", "UNKNOWN")
        
        if relay_state == "AKTIF":
            icon = "🔴"
            bg_color = "#dc3545"
        else:
            icon = "🟢"
            bg_color = "#28a745"
        
        st.markdown(f"""
        <div style="background-color: {bg_color}; padding: 15px; border-radius: 10px; color: white; text-align: center;">
            <div style="font-size: 14px;">{icon} Status Relay</div>
            <div style="font-size: 24px; font-weight: bold; margin: 5px 0;">{relay_state}</div>
            <div style="font-size: 16px;">{voltage:.1f} V</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        lamp_state = data.get("lamp_state", "UNKNOWN")
        
        if lamp_state == "MENYALA":
            icon = "💡"
            bg_color = "#FFD700"
            text_color = "black"
        else:
            icon = "🌙"
            bg_color = "#2E4053"
            text_color = "white"
        
        st.markdown(f"""
        <div style="background-color: {bg_color}; padding: 15px; border-radius: 10px; color: {text_color}; text-align: center;">
            <div style="font-size: 14px;">Status Lampu</div>
            <div style="font-size: 36px; margin: 10px 0;">{icon}</div>
            <div style="font-size: 20px; font-weight: bold;">{lamp_state}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        timestamp = data.get("timestamp")
        if isinstance(timestamp, datetime):
            time_str = timestamp.strftime("%H:%M:%S")
            date_str = timestamp.strftime("%Y-%m-%d")
        else:
            time_str = "N/A"
            date_str = "N/A"
        
        st.markdown(f"""
        <div style="background-color: #0d6efd; padding: 15px; border-radius: 10px; color: white; text-align: center;">
            <div style="font-size: 14px;">🕐 Update Terakhir</div>
            <div style="font-size: 24px; font-weight: bold; margin: 5px 0;">{time_str}</div>
            <div style="font-size: 14px;">{date_str}</div>
        </div>
        """, unsafe_allow_html=True)
else:
    st.info("📭 **Belum ada data** - Tunggu data dari ESP32 atau pastikan MQTT terhubung")

# ==================== VISUALISASI DATA ====================
st.header("📈 VISUALISASI DATA")

if st.session_state.logs:
    logs_list = st.session_state.logs[-MAX_POINTS:]
    df = pd.DataFrame(logs_list)
    
    if not df.empty and "intensity" in df.columns:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            # Line chart
            fig = go.Figure()
            
            fig.add_trace(go.Scatter(
                x=df["timestamp"],
                y=df["intensity"],
                mode="lines+markers",
                name="Intensitas Cahaya",
                line=dict(color="#FFA500", width=3),
                marker=dict(size=8)
            ))
            
            # Add voltage as second y-axis if available
            if "voltage" in df.columns:
                fig.add_trace(go.Scatter(
                    x=df["timestamp"],
                    y=df["voltage"],
                    mode="lines",
                    name="Tegangan",
                    line=dict(color="#0d6efd", width=2, dash="dash"),
                    yaxis="y2"
                ))
                
                fig.update_layout(
                    yaxis2=dict(
                        title="Tegangan (V)",
                        overlaying="y",
                        side="right",
                        showgrid=False
                    )
                )
            
            # Add threshold line
            fig.add_hline(
                y=50,
                line_dash="dash",
                line_color="red",
                annotation_text="Threshold (50%)",
                annotation_position="bottom right"
            )
            
            fig.update_layout(
                title="TREN INTENSITAS CAHAYA",
                height=400,
                xaxis_title="Waktu",
                yaxis_title="Intensitas (%)",
                hovermode="x unified",
                showlegend=True
            )
            
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Gauge chart
            if st.session_state.last_data:
                intensity = st.session_state.last_data.get("intensity", 50)
                st.plotly_chart(create_intensity_gauge(intensity), use_container_width=True)
            
            # Statistics
            stats = calculate_statistics()
            
            st.metric("📊 Rata-rata Intensitas", f"{stats['avg_intensity']}%")
            st.metric("💡 Lampu Menyala", f"{stats['lamp_on_percentage']}%")
            st.metric("📈 Total Data", f"{stats['total_data']}")
            st.metric("🕐 Update Terakhir", stats['latest_timestamp'])
    else:
        st.warning("Data tidak lengkap untuk visualisasi")
else:
    st.info("📭 **Belum ada data untuk divisualisasikan**")

# ==================== KONTROL MANUAL ====================
st.header("🎛️ KONTROL MANUAL")

if st.session_state.mqtt_connected:
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns(3)
    
    with col_ctrl1:
        if st.button("💡 NYALAKAN LAMPU", use_container_width=True, type="primary"):
            try:
                pub_client = mqtt.Client()
                pub_client.connect(MQTT_BROKER, MQTT_PORT, 60)
                pub_client.publish(MQTT_TOPIC_CONTROL, "LAMP_ON")
                pub_client.disconnect()
                st.success("Perintah NYALAKAN LAMPU dikirim")
            except Exception as e:
                st.error(f"Gagal mengirim perintah: {e}")
    
    with col_ctrl2:
        if st.button("🌙 MATIKAN LAMPU", use_container_width=True):
            try:
                pub_client = mqtt.Client()
                pub_client.connect(MQTT_BROKER, MQTT_PORT, 60)
                pub_client.publish(MQTT_TOPIC_CONTROL, "LAMP_OFF")
                pub_client.disconnect()
                st.success("Perintah MATIKAN LAMPU dikirim")
            except Exception as e:
                st.error(f"Gagal mengirim perintah: {e}")
    
    with col_ctrl3:
        if st.button("🔄 STATUS SYSTEM", use_container_width=True, type="secondary"):
            try:
                pub_client = mqtt.Client()
                pub_client.connect(MQTT_BROKER, MQTT_PORT, 60)
                pub_client.publish(MQTT_TOPIC_CONTROL, "GET_STATUS")
                pub_client.disconnect()
                st.success("Request status dikirim")
            except Exception as e:
                st.error(f"Gagal mengirim request: {e}")
else:
    st.warning("⚠️ Koneksi MQTT diperlukan untuk kontrol manual")

# ==================== DATA HISTORIS ====================
st.header("📋 DATA HISTORIS")

if st.session_state.logs:
    logs_list = st.session_state.logs[-100:]  # Last 100 records
    df_display = pd.DataFrame(logs_list)
    
    if not df_display.empty:
        # Format for display
        df_display["waktu"] = df_display["timestamp"].apply(
            lambda x: x.strftime("%H:%M:%S") if isinstance(x, datetime) else str(x)[11:19]
        )
        
        display_cols = ["waktu", "intensity", "voltage", "relay_state", "lamp_state"]
        display_df = df_display[display_cols].copy()
        
        # Format values
        display_df["intensity"] = display_df["intensity"].apply(lambda x: f"{x:.1f}%" if pd.notnull(x) else "N/A")
        display_df["voltage"] = display_df["voltage"].apply(lambda x: f"{x:.1f}V" if pd.notnull(x) else "N/A")
        
        display_df.columns = ["Waktu", "Intensitas", "Tegangan", "Relay", "Lampu"]
        
        st.dataframe(
            display_df,
            hide_index=True,
            use_container_width=True,
            height=300
        )
        
        # Download button
        csv = display_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Data CSV",
            data=csv,
            file_name=f"streetlight_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )
else:
    st.info("📭 Tidak ada data historis")

# ==================== DIAGNOSTIC PANEL ====================
with st.expander("🔍 PANEL DIAGNOSTIK", expanded=False):
    diag_col1, diag_col2 = st.columns(2)
    
    with diag_col1:
        st.subheader("🔄 Status Sistem")
        st.write(f"**MQTT Worker:** {'✅ Berjalan' if st.session_state.mqtt_thread_started else '❌ Berhenti'}")
        st.write(f"**Koneksi MQTT:** {'✅ Terhubung' if st.session_state.mqtt_connected else '❌ Terputus'}")
        st.write(f"**Status:** {st.session_state.connection_status}")
        st.write(f"**Data dalam queue:** {GLOBAL_MQ.qsize()}")
        st.write(f"**Total data:** {len(st.session_state.logs)}")
        
        if st.button("🩺 Refresh Diagnostics", key="refresh_diag"):
            st.rerun()
    
    with diag_col2:
        st.subheader("🌐 Network Test")
        if st.button("Test Broker Connection", use_container_width=True):
            with st.spinner("Testing broker.hivemq.com..."):
                success, error = test_broker_connection()
                if success:
                    st.success("✅ Broker dapat diakses dari server ini")
                else:
                    st.error(f"❌ Broker tidak dapat diakses: {error}")

# ==================== FOOTER ====================
st.divider()

footer_col1, footer_col2 = st.columns([1, 3])

with footer_col2:
    status_icon = "🟢" if st.session_state.mqtt_connected else "🔴"
    
    st.markdown(f"""
    <div style="text-align: right; color: #666; font-size: 12px; padding: 10px;">
        <p>💡 <strong>Smart Streetlight Dashboard</strong> | 
        Status: {status_icon} {st.session_state.connection_status} | 
        Data: {len(st.session_state.logs)} records | 
        Update: {datetime.now().strftime('%H:%M:%S')}</p>
    </div>
    """, unsafe_allow_html=True)

# Process any remaining messages
process_queue()

# CSS Styling
st.markdown("""
<style>
    /* Custom styling */
    div[data-testid="stMetricValue"] {
        font-size: 24px;
        font-weight: bold;
    }
    
    div[data-testid="stMetricDelta"] {
        font-size: 14px;
    }
    
    .stButton button {
        transition: all 0.3s ease;
    }
    
    .stButton button:hover {
        transform: translateY(-1px);
        box-shadow: 0 3px 6px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)