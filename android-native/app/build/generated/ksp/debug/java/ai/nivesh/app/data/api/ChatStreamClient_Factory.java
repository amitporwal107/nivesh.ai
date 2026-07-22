package ai.nivesh.app.data.api;

import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;
import kotlinx.serialization.json.Json;
import okhttp3.OkHttpClient;

@ScopeMetadata("javax.inject.Singleton")
@QualifierMetadata
@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class ChatStreamClient_Factory implements Factory<ChatStreamClient> {
  private final Provider<OkHttpClient> clientProvider;

  private final Provider<Json> jsonProvider;

  public ChatStreamClient_Factory(Provider<OkHttpClient> clientProvider,
      Provider<Json> jsonProvider) {
    this.clientProvider = clientProvider;
    this.jsonProvider = jsonProvider;
  }

  @Override
  public ChatStreamClient get() {
    return newInstance(clientProvider.get(), jsonProvider.get());
  }

  public static ChatStreamClient_Factory create(Provider<OkHttpClient> clientProvider,
      Provider<Json> jsonProvider) {
    return new ChatStreamClient_Factory(clientProvider, jsonProvider);
  }

  public static ChatStreamClient newInstance(OkHttpClient client, Json json) {
    return new ChatStreamClient(client, json);
  }
}
