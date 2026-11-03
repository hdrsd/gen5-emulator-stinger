package test.emulator.config;
import android.os.Binder;
import android.os.IBinder;
import android.os.Parcel;
import android.os.RemoteException;

/** Emulator-only: acknowledge hardware-bound raw sends, forward all other calls. */
public class MicomSendProxy extends Binder {
  private static final String DESCRIPTOR="com.lge.ivi.IIVIMessageService";
  private final IBinder original;
  public MicomSendProxy(IBinder original) {this.original=original;attachInterface(null,DESCRIPTOR);}
  @Override protected boolean onTransact(int code,Parcel data,Parcel reply,int flags) throws RemoteException {
    if(code==IBinder.INTERFACE_TRANSACTION) {reply.writeString(DESCRIPTOR);return true;}
    if(code==0x5f434b) {data.enforceInterface(DESCRIPTOR);reply.writeNoException();reply.writeInt(0x4d49434f);return true;}
    if(code==6) {data.enforceInterface(DESCRIPTOR);reply.writeNoException();return true;}
    return original!=null && original.transact(code,data,reply,flags);
  }
  public static void main(String[] args) throws Exception {
    Class<?> sm=Class.forName("android.os.ServiceManager");
    String name="com.lge.ivi.server.Micom";
    IBinder original=(IBinder)sm.getMethod("getService",String.class).invoke(null,name);
    if(original==null)throw new IllegalStateException("Original IVI message service is absent");
    sm.getMethod("addService",String.class,IBinder.class).invoke(null,name,new MicomSendProxy(original));
    System.out.println("EXPERIMENTAL MICOM SEND PROXY REGISTERED");
    Class.forName("com.android.internal.os.BinderInternal").getMethod("joinThreadPool").invoke(null);
  }
}
