package test.emulator.config;
import android.os.Binder;
import android.os.IBinder;
import android.os.Parcel;
import android.os.RemoteException;
import java.lang.reflect.Field;
import java.util.HashMap;

/** Emulator-only Bluetooth manager reporting that no Bluetooth device is available. */
public class BluetoothManagerStub extends Binder {
  private static final String DESCRIPTOR="android.bluetooth.IBluetoothManager";
  private final HashMap<Integer,String> names = new HashMap<Integer,String>();
  public BluetoothManagerStub() throws Exception {
    attachInterface(null, DESCRIPTOR);
    Class<?> c=Class.forName("android.bluetooth.IBluetoothManager$Stub");
    for (Field f:c.getDeclaredFields()) if(f.getName().startsWith("TRANSACTION_")) {
      f.setAccessible(true); names.put(f.getInt(null),f.getName().substring(12));
    }
    System.out.println("Bluetooth manager transaction map: "+names);
  }
  @Override protected boolean onTransact(int code,Parcel data,Parcel reply,int flags) throws RemoteException {
    if(code==IBinder.INTERFACE_TRANSACTION) {reply.writeString(DESCRIPTOR);return true;}
    String name=names.get(code);
    if(name==null) {System.out.println("Unknown Bluetooth transaction "+code);return false;}
    data.enforceInterface(DESCRIPTOR);
    reply.writeNoException();
    if(name.equals("registerAdapter") || name.equals("getBluetoothGatt")) reply.writeStrongBinder(null);
    else if(name.equals("getAddress") || name.equals("getName")) reply.writeString(null);
    else if(name.equals("isEnabled") || name.startsWith("enable") || name.equals("disable") || name.startsWith("is")) reply.writeInt(0);
    return true;
  }
  public static void main(String[] args) throws Exception {
    Class<?> sm=Class.forName("android.os.ServiceManager");
    sm.getMethod("addService",String.class,IBinder.class).invoke(null,"bluetooth_manager",new BluetoothManagerStub());
    System.out.println("EMULATED BLUETOOTH MANAGER REGISTERED (NO DEVICE)");
    Class.forName("com.android.internal.os.BinderInternal").getMethod("joinThreadPool").invoke(null);
  }
}
