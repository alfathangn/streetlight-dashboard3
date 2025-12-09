import streamlit as st
import pandas as pd
import json
import time
import paho.mqtt.client as mqtt
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
import socket

# ==================== KONFIGURASI MQTT ====================
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC_SENSOR = "iot/streetlight"
MQTT_TOPIC_CONTROL = "iot/streetlight/control"

# ==================== SESSION STATE INIT ====================
if "mqtt_connected" not in st.session_state:
    st.session_state.mqtt_connected = False

if "connection_status" not in st.session_state:
    st.session_state.connection_status = "❌ TIDAK TERKONEKSI"

if "connection_error" not in st.session_state:
    st.session_state.connection_error = ""

if "logs" not in st.session_state:
    st.session_state.logs = []

if "last_data" not in st.session_state:
    st.session_state.last_data = None

if "mqtt_client" not in st.session_state:
    st.session_state.mqtt_client = None

if "broker_test_result" not in st.session_state:
    st.session_state.broker_test_result = None

if "last_connection_attempt" not in st.session_state:
    st.session_state.last_connection_attempt = "Belum pernah"

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
def on_connect(client, userdata, flags, rc, properties=None):
    """Callback ketika koneksi MQTT berhasil/gagal"""
    if rc == 0:
        st.session_state.mqtt_connected = True
        st.session_state.connection_status = "✅ TERKONEKSI"
        st.session_state.connection_error = ""
        client.subscribe(MQTT_TOPIC_SENSOR)
        print(f"✅ Connected to MQTT broker")
        print(f"✅ Subscribed to topic: {MQTT_TOPIC_SENSOR}")
    else:
        st.session_state.mqtt_connected = False
        error_messages = {
            1: "Incorrect protocol version",
            2: "Invalid client identifier",
            3: "Server unavailable",
            4: "Bad username or password",
            5: "Not authorized"
        }
        error_msg = error_messages.get(rc, f"Error code: {rc}")
        st.session_state.connection_status = f"❌ {error_msg}"
        st.session_state.connection_error = error_msg
        print(f"❌ Connection failed: {error_msg}")

def on_disconnect(client, userdata, rc):
    """Callback ketika terputus dari MQTT"""
    st.session_state.mqtt_connected = False
    st.session_state.connection_status = "❌ TERPUTUS"
    print(f"⚠️ Disconnected from MQTT broker")

def on_message(client, userdata, msg):
    """Callback ketika menerima pesan MQTT"""
    try:
        payload = msg.payload.decode('utf-8', errors='ignore')
        print(f"📥 Received MQTT message: {payload}")
        
        # Parse data dari ESP32 (format: {timestamp;intensity;voltage})
        if payload.startswith("{") and payload.endswith("}"):
            clean_payload = payload[1:-1]  # Remove curly braces
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
                
                # Determine states berdasarkan logika ESP32
                if voltage == 0.0:
                    relay_state = "MATI"
                    lamp_state = "MENYALA"
                elif voltage == 220.0:
                    relay_state = "AKTIF"
                    lamp_state = "MATI"
                else:
                    relay_state = "UNKNOWN"
                    lamp_state = "UNKNOWN"
                
                # Create data row
                row = {
                    "timestamp": timestamp,
                    "intensity": intensity,
                    "voltage": voltage,
                    "relay_state": relay_state,
                    "lamp_state": lamp_state,
                    "source": "MQTT REAL"
                }
                
                # Update session state
                st.session_state.last_data = row
                st.session_state.logs.append(row)
                
                # Keep logs bounded
                if len(st.session_state.logs) > 1000:
                    st.session_state.logs = st.session_state.logs[-1000:]
                
                print(f"✅ Parsed: Intensity={intensity}, Voltage={voltage}, Relay={relay_state}")
                
    except Exception as e:
        print(f"❌ Error processing MQTT message: {e}")

# ==================== FUNGSI KONEKSI MQTT ====================
def connect_mqtt():
    """Connect to MQTT broker"""
    try:
        # Test broker connection first
        success, error = test_broker_connection()
        if not success:
            st.session_state.connection_status = f"❌ Broker tidak dapat diakses: {error}"
            st.session_state.connection_error = error
            return False
        
        # Create MQTT client
        client = mqtt.Client()
        client.on_connect = on_connect
        client.on_message = on_message
        client.on_disconnect = on_disconnect
        
        # Connect
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        st.session_state.mqtt_client = client
        st.session_state.last_connection_attempt = datetime.now().strftime("%H:%M:%S")
        
        return True
        
    except Exception as e:
        st.session_state.connection_status = f"❌ Connection error: {str(e)}"
        st.session_state.connection_error = str(e)
        print(f"❌ Connection failed: {e}")
        return False

def disconnect_mqtt():
    """Disconnect from MQTT broker"""
    if st.session_state.mqtt_client:
        try:
            st.session_state.mqtt_client.disconnect()
        except:
            pass
    st.session_state.mqtt_connected = False
    st.session_state.connection_status = "❌ TIDAK TERKONEKSI"
    st.session_state.mqtt_client = None

# ==================== STREAMLIT UI ====================
st.set_page_config(
    page_title="Smart Streetlight Dashboard",
    page_icon="💡",
    layout="wide"
)

st.title("💡 SMART STREETLIGHT MONITORING SYSTEM")

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
    
    st.write(f"**Terakhir dicoba:** {st.session_state.last_connection_attempt}")
    
    # Connection Buttons
    st.markdown("---")
    st.subheader("🔄 KONTROL MQTT")
    
    # Connect Button
    if st.button("🔗 Sambungkan ke MQTT", use_container_width=True, type="primary"):
        with st.spinner("Menghubungkan ke MQTT broker..."):
            if connect_mqtt():
                st.success("✅ Berhasil menghubungkan ke broker")
                st.session_state.broker_test_result = "✅ SUCCESS"
            else:
                st.error("❌ Gagal menghubungkan ke broker")
                st.session_state.broker_test_result = "❌ FAILED"
        time.sleep(1)
        st.rerun()
    
    # Disconnect Button
    if st.button("🔌 Putuskan Koneksi", use_container_width=True):
        disconnect_mqtt()
        st.warning("Koneksi MQTT diputuskan")
        time.sleep(1)
        st.rerun()
    
    # Test Connection Button
    if st.button("🧪 Test Koneksi Broker", use_container_width=True):
        with st.spinner("Testing koneksi ke broker..."):
            success, error = test_broker_connection()
            if success:
                st.success("✅ Broker dapat diakses dari server ini")
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
        1. ✅ Buka Serial Monitor ESP32 (115200 baud)
        2. ✅ Cek pesan "✓ WiFi connected!"
        3. ✅ Cek pesan "✓ MQTT connected!"
        4. ✅ Cek pesan "📤 MQTT Sent: {...}"
        5. ✅ Test di: http://www.hivemq.com/demos/websocket-client/
           - Connect to: broker.hivemq.com:1883
           - Subscribe to: iot/streetlight
        """)

# ==================== MQTT LOOP POLLING ====================
# Process MQTT messages if connected
if st.session_state.mqtt_client:
    try:
        st.session_state.mqtt_client.loop(timeout=0.1)
    except Exception as e:
        print(f"MQTT loop error: {e}")

# ==================== MAIN DASHBOARD ====================
# Status Banner
if not st.session_state.mqtt_connected:
    st.error("""
    ⚠️ **MQTT TIDAK TERKONEKSI!** 
    
    Silakan klik tombol "Sambungkan ke MQTT" di sidebar untuk menghubungkan ke broker.
    
    **Pastikan:**
    1. ESP32 menyala dan terhubung ke WiFi
    2. ESP32 mengirim data ke topic: `iot/streetlight`
    3. Format data: `{timestamp;intensity;voltage}`
    """)
else:
    if st.session_state.last_data:
        st.success(f"✅ **TERHUBUNG KE MQTT BROKER** - Data terakhir: {st.session_state.last_data.get('timestamp').strftime('%H:%M:%S')}")
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
            # Determine status based on intensity
            if intensity < 30:
                color = "🟢"
                status_text = "GELAP"
                status_color = "normal"
                intensity_desc = "Lampu MENYALA"
            elif intensity < 70:
                color = "🟡"
                status_text = "SEDANG"
                status_color = "off"
                intensity_desc = "Kondisi Normal"
            else:
                color = "🔵"
                status_text = "TERANG"
                status_color = "inverse"
                intensity_desc = "Lampu MATI"
            
            st.metric(
                label=f"{color} Intensitas Cahaya",
                value=f"{intensity:.1f}%",
                delta=f"{status_text}",
                delta_color=status_color,
                help=intensity_desc
            )
        else:
            st.metric("Intensitas Cahaya", "N/A")
    
    with col2:
        voltage = data.get("voltage")
        relay_state = data.get("relay_state", "UNKNOWN")
        
        if relay_state == "AKTIF":
            icon = "🔴"
            bg_color = "#dc3545"
            status_desc = "Tegangan 220V - Relay ON"
        elif relay_state == "MATI":
            icon = "🟢"
            bg_color = "#28a745"
            status_desc = "Tegangan 0V - Relay OFF"
        else:
            icon = "❓"
            bg_color = "#6c757d"
            status_desc = "Status tidak diketahui"
        
        st.markdown(f"""
        <div style="background-color: {bg_color}; padding: 15px; border-radius: 10px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9;">{icon} Status Relay</div>
            <div style="font-size: 24px; font-weight: bold; margin: 5px 0;">{relay_state}</div>
            <div style="font-size: 16px;">{voltage if voltage is not None else 'N/A'} V</div>
        </div>
        """, unsafe_allow_html=True)
        st.caption(status_desc)
    
    with col3:
        lamp_state = data.get("lamp_state", "UNKNOWN")
        
        if lamp_state == "MENYALA":
            icon = "💡"
            bg_color = "#FFD700"
            text_color = "black"
            lamp_desc = "Lampu sedang menyala"
        elif lamp_state == "MATI":
            icon = "🌙"
            bg_color = "#2E4053"
            text_color = "white"
            lamp_desc = "Lampu mati"
        else:
            icon = "❓"
            bg_color = "#6c757d"
            text_color = "white"
            lamp_desc = "Status tidak diketahui"
        
        st.markdown(f"""
        <div style="background-color: {bg_color}; padding: 15px; border-radius: 10px; color: {text_color}; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9;">Status Lampu</div>
            <div style="font-size: 36px; margin: 10px 0;">{icon}</div>
            <div style="font-size: 20px; font-weight: bold;">{lamp_state}</div>
        </div>
        """, unsafe_allow_html=True)
        st.caption(lamp_desc)
    
    with col4:
        timestamp = data.get("timestamp")
        if isinstance(timestamp, datetime):
            time_str = timestamp.strftime("%H:%M:%S")
            date_str = timestamp.strftime("%Y-%m-%d")
        else:
            time_str = "N/A"
            date_str = "N/A"
        
        data_count = len(st.session_state.logs)
        
        st.markdown(f"""
        <div style="background-color: #0d6efd; padding: 15px; border-radius: 10px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9;">📊 Info Sistem</div>
            <div style="font-size: 20px; font-weight: bold; margin: 5px 0;">{time_str}</div>
            <div style="font-size: 12px;">{date_str}</div>
            <div style="font-size: 12px; margin-top: 5px;">Data: {data_count} records</div>
        </div>
        """, unsafe_allow_html=True)
        st.caption("Update terakhir")
else:
    st.info("📭 **Belum ada data** - Tunggu data dari ESP32 atau sambungkan ke MQTT terlebih dahulu")

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
    if "timestamp" in df.columns:
        latest_timestamp = df["timestamp"].max()
        if isinstance(latest_timestamp, datetime):
            latest_timestamp = latest_timestamp.strftime("%H:%M:%S")
        else:
            latest_timestamp = "N/A"
    else:
        latest_timestamp = "N/A"
    
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

# ==================== VISUALISASI DATA ====================
st.header("📈 VISUALISASI DATA")

if st.session_state.logs:
    logs_list = st.session_state.logs[-200:]  # Last 200 points
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
            
            # Add threshold line
            fig.add_hline(
                y=50,
                line_dash="dash",
                line_color="red",
                annotation_text="Threshold (50%)",
                annotation_position="bottom right"
            )
            
            # Color markers by lamp state if available
            if "lamp_state" in df.columns:
                colors = df["lamp_state"].apply(lambda x: "#FFD700" if x == "MENYALA" else "#2E4053")
                fig.update_traces(marker=dict(color=colors))
            
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
            st.metric("⚡ Tegangan Rata-rata", f"{stats['avg_voltage']}V")
            st.metric("📈 Total Data", f"{stats['total_data']}")
    else:
        st.warning("Data tidak lengkap untuk visualisasi")
else:
    st.info("📭 **Belum ada data untuk divisualisasikan**")

# ==================== DATA HISTORIS ====================
st.header("📋 DATA HISTORIS")

if st.session_state.logs:
    logs_list = st.session_state.logs[-50:]  # Last 50 records
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
        st.write(f"**Koneksi MQTT:** {'✅ Terhubung' if st.session_state.mqtt_connected else '❌ Terputus'}")
        st.write(f"**Status:** {st.session_state.connection_status}")
        st.write(f"**Client MQTT:** {'✅ Ada' if st.session_state.mqtt_client else '❌ Tidak ada'}")
        st.write(f"**Total data:** {len(st.session_state.logs)}")
        st.write(f"**Data terakhir:** {st.session_state.last_connection_attempt}")
        
        if st.button("🩺 Refresh Diagnostics", key="refresh_diag"):
            st.rerun()
    
    with diag_col2:
        st.subheader("🌐 Network Test")
        if st.button("Test Broker Connection", use_container_width=True, key="test_broker_diag"):
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

# Auto-refresh
time.sleep(2)
st.rerun()
