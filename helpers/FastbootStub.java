package test.emulator.config;
import android.os.Binder;
import android.os.IBinder;
import android.os.Parcel;
import android.os.RemoteException;

/** Experiment only: model the missing IVI fastboot readiness callbacks. */
public class FastbootStub extends Binder {
  private static final String SERVICE="com.lge.ivi.IIviFastbootService";
  private static final String LISTENER="com.lge.ivi.IIviFastbootStateListener";
  public FastbootStub() { attachInterface(null,SERVICE); }
  @Override protected boolean onTransact(int code,Parcel data,Parcel reply,int flags) throws RemoteException {
    if(code==IBinder.INTERFACE_TRANSACTION) { reply.writeString(SERVICE);return true; }
    if(code>=1 && code<=7) {
      data.enforceInterface(SERVICE);
      if(code==1) {
        new Thread(new CallbackTask(data.readStrongBinder())).start();
      } else if(code==2) {data.readStrongBinder();}
      else if(code==3) {data.readInt();}
      reply.writeNoException(); if(code>=3) reply.writeInt(1);
      return true;
    }
    return super.onTransact(code,data,reply,flags);
  }
  public static void main(String[] args) throws Exception {
    Class<?> sm=Class.forName("android.os.ServiceManager");
    sm.getMethod("addService",String.class,IBinder.class).invoke(null,"com.lge.ivi.server.Fastboot",new FastbootStub());
    System.out.println("EXPERIMENTAL FASTBOOT PLACEHOLDER REGISTERED");
    Class.forName("com.android.internal.os.BinderInternal").getMethod("joinThreadPool").invoke(null);
  }
}

class CallbackTask implements Runnable {
  private final IBinder listener;
  CallbackTask(IBinder listener) {this.listener=listener;}
  public void run() {
    try {
      Thread.sleep(1000);
      for(int event=1;event<=3;event++) {
        Parcel req=Parcel.obtain(),res=Parcel.obtain();
        try {req.writeInterfaceToken("com.lge.ivi.IIviFastbootStateListener");listener.transact(event,req,res,0);res.readException();}
        finally {req.recycle();res.recycle();}
      }
    } catch(Exception e) {System.err.println("callback: "+e);}
  }
}
