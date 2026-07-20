package ai.nivesh.app.data.repo;

import ai.nivesh.app.data.api.ChatStreamClient;
import ai.nivesh.app.data.api.NiveshApi;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

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
public final class ChatRepository_Factory implements Factory<ChatRepository> {
  private final Provider<NiveshApi> apiProvider;

  private final Provider<ChatStreamClient> streamClientProvider;

  public ChatRepository_Factory(Provider<NiveshApi> apiProvider,
      Provider<ChatStreamClient> streamClientProvider) {
    this.apiProvider = apiProvider;
    this.streamClientProvider = streamClientProvider;
  }

  @Override
  public ChatRepository get() {
    return newInstance(apiProvider.get(), streamClientProvider.get());
  }

  public static ChatRepository_Factory create(Provider<NiveshApi> apiProvider,
      Provider<ChatStreamClient> streamClientProvider) {
    return new ChatRepository_Factory(apiProvider, streamClientProvider);
  }

  public static ChatRepository newInstance(NiveshApi api, ChatStreamClient streamClient) {
    return new ChatRepository(api, streamClient);
  }
}
