package test.emulator.config;
import android.os.Binder;
import android.os.IBinder;
import android.os.Parcel;
import android.os.RemoteException;
public class CameraStub extends Binder {
  private static final String DESCRIPTOR="com.lge.ivi.auxcamera.IAuxCameraManager";
  public CameraStub() { attachInterface(null,DESCRIPTOR); }
  @Override protected boolean onTransact(int code,Parcel data,Parcel reply,int flags) throws RemoteException {
    if(code==IBinder.INTERFACE_TRANSACTION) {reply.writeString(DESCRIPTOR);return true;}
    if(code>=1 && code<=40) {data.enforceInterface(DESCRIPTOR);reply.writeNoException();reply.writeInt(0);return true;}
    return super.onTransact(code,data,reply,flags);
  }
  public static void main(String[] args) throws Exception {
    Class<?> sm=Class.forName("android.os.ServiceManager");
    sm.getMethod("addService",String.class,IBinder.class).invoke(null,"com.lge.ivi.auxcamera.AuxCameraManager",new CameraStub());
    System.out.println("EMULATOR CAMERA PLACEHOLDER REGISTERED");
    Class.forName("com.android.internal.os.BinderInternal").getMethod("joinThreadPool").invoke(null);
  }
}
