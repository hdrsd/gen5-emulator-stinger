package test.emulator.config;
import android.os.Binder;
import android.os.IBinder;
import android.os.Parcel;
import android.os.RemoteException;

/** Virtual-only proxy: acknowledge the absent navigation license-confirm response. */
public class NaviConfirmProxy extends Binder {
  private static final String DESCRIPTOR="com.lge.ivi.navi.INavi";
  private final IBinder original;
  public NaviConfirmProxy(IBinder original) {this.original=original;attachInterface(null,DESCRIPTOR);}
  @Override protected boolean onTransact(int code,Parcel data,Parcel reply,int flags) throws RemoteException {
    if(code==IBinder.INTERFACE_TRANSACTION) {reply.writeString(DESCRIPTOR);return true;}
    if(code==0x5f434b) {data.enforceInterface(DESCRIPTOR);reply.writeNoException();reply.writeInt(0x4e415649);return true;}
    if(code==0x2e) {
      data.enforceInterface(DESCRIPTOR);
      System.out.println("VIRTUAL NAVIGATION CONFIRM RECEIVED");
      try {
        Class<?> props=Class.forName("android.os.SystemProperties");
        props.getMethod("set",String.class,String.class).invoke(null,"service.bootanim.exit","1");
      } catch(Exception e) {throw new RemoteException("Could not persist virtual consent state: "+e);}
      System.out.println("VIRTUAL NAVIGATION CONFIRM ACCEPTED");
      reply.writeNoException();return true;
    }
    return original!=null && original.transact(code,data,reply,flags);
  }
  public static void main(String[] args) throws Exception {
    Class<?> sm=Class.forName("android.os.ServiceManager");
    String name="com.lge.ivi.navi.NaviManager";
    IBinder original=(IBinder)sm.getMethod("getService",String.class).invoke(null,name);
    sm.getMethod("addService",String.class,IBinder.class).invoke(null,name,new NaviConfirmProxy(original));
    System.out.println("EXPERIMENTAL NAVI CONFIRM PROXY REGISTERED, original="+(original!=null));
    Class.forName("com.android.internal.os.BinderInternal").getMethod("joinThreadPool").invoke(null);
  }
}
