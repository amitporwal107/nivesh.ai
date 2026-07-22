package ai.nivesh.app.ui.chat;

import ai.nivesh.app.data.repo.ChatRepository;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata
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
public final class ChatViewModel_Factory implements Factory<ChatViewModel> {
  private final Provider<ChatRepository> repoProvider;

  public ChatViewModel_Factory(Provider<ChatRepository> repoProvider) {
    this.repoProvider = repoProvider;
  }

  @Override
  public ChatViewModel get() {
    return newInstance(repoProvider.get());
  }

  public static ChatViewModel_Factory create(Provider<ChatRepository> repoProvider) {
    return new ChatViewModel_Factory(repoProvider);
  }

  public static ChatViewModel newInstance(ChatRepository repo) {
    return new ChatViewModel(repo);
  }
}
